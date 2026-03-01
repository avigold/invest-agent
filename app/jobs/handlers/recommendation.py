"""Recommendation analysis job handler.

Generates AI-powered analysis for a specific company's recommendation,
including country, industry, and company context from decision packets.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import desc, select

from app.analysis.recommendation_analysis import generate_analysis
from app.db.models import (
    Company,
    Country,
    DecisionPacket,
    Industry,
)
from app.score.recommendations import compute_recommendations
from app.score.versions import (
    COMPANY_SUMMARY_VERSION,
    COUNTRY_SUMMARY_VERSION,
    INDUSTRY_SUMMARY_VERSION,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.jobs.registry import LiveJob


def _log(job: LiveJob, msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def _latest_packet(
    db: AsyncSession, packet_type: str, entity_id, summary_version: str
) -> DecisionPacket | None:
    result = await db.execute(
        select(DecisionPacket)
        .where(
            DecisionPacket.packet_type == packet_type,
            DecisionPacket.entity_id == entity_id,
            DecisionPacket.summary_version == summary_version,
        )
        .order_by(desc(DecisionPacket.as_of))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def recommendation_analysis_handler(
    job: LiveJob,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Generate AI analysis for a company's recommendation."""
    ticker = job.params.get("ticker", "").upper()
    if not ticker:
        _log(job, "ERROR: 'ticker' param is required")
        job.status = "failed"
        return

    _log(job, f"Generating recommendation analysis for {ticker}")

    async with session_factory() as db:
        # Compute all recommendations and find this ticker
        _log(job, "Computing recommendations...")
        recommendations = await compute_recommendations(db)
        rec = next((r for r in recommendations if r["ticker"] == ticker), None)
        if rec is None:
            _log(job, f"ERROR: No recommendation found for '{ticker}'")
            job.status = "failed"
            return

        _log(job, f"Found: {rec['name']} — {rec['classification']} ({rec['composite_score']})")

        # Fetch entity records for packet lookups
        company_result = await db.execute(select(Company).where(Company.ticker == ticker))
        company = company_result.scalar_one_or_none()

        country_result = await db.execute(select(Country).where(Country.iso2 == rec["country_iso2"]))
        country = country_result.scalar_one_or_none()

        industry_result = await db.execute(select(Industry).where(Industry.gics_code == rec["gics_code"]))
        industry = industry_result.scalar_one_or_none()

        # Fetch latest decision packets
        packets: dict[str, dict | None] = {"country": None, "industry": None, "company": None}

        if country:
            pkt = await _latest_packet(db, "country", country.id, COUNTRY_SUMMARY_VERSION)
            packets["country"] = pkt.content if pkt else None
            _log(job, f"Country packet: {'found' if pkt else 'not found'}")

        if industry and country:
            industry_entity_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{industry.id}:{country.id}")
            pkt = await _latest_packet(db, "industry", industry_entity_id, INDUSTRY_SUMMARY_VERSION)
            packets["industry"] = pkt.content if pkt else None
            _log(job, f"Industry packet: {'found' if pkt else 'not found'}")

        if company:
            pkt = await _latest_packet(db, "company", company.id, COMPANY_SUMMARY_VERSION)
            packets["company"] = pkt.content if pkt else None
            _log(job, f"Company packet: {'found' if pkt else 'not found'}")

        # Generate analysis (checks cache internally)
        try:
            result = await generate_analysis(
                db, rec, packets, log=lambda msg: _log(job, msg)
            )
        except ValueError as e:
            _log(job, f"ERROR: {e}")
            job.status = "failed"
            return
        except Exception as e:
            _log(job, f"ERROR: {e}")
            job.status = "failed"
            return

        _log(job, f"Analysis complete: {len(result.get('summary', ''))} chars in summary")
        _log(job, "Done.")
