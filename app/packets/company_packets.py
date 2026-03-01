"""Company decision packet builder."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Artefact,
    Company,
    CompanyRiskRegister,
    CompanyScore,
    CompanySeries,
    CompanySeriesPoint,
    DecisionPacket,
)
from app.score.versions import COMPANY_SUMMARY_VERSION


async def build_company_packet(
    db: AsyncSession,
    company: Company,
    score: CompanyScore,
    risks: list[CompanyRiskRegister],
    all_scores: list[CompanyScore],
    include_evidence: bool = False,
) -> DecisionPacket:
    """Build a decision packet from stored scores and evidence."""
    # Compute rank among all companies
    sorted_scores = sorted(all_scores, key=lambda s: float(s.overall_score), reverse=True)
    rank = 1
    for i, s in enumerate(sorted_scores):
        if s.company_id == company.id:
            rank = i + 1
            break

    content: dict = {
        "ticker": company.ticker,
        "cik": company.cik,
        "company_name": company.name,
        "gics_code": company.gics_code,
        "country_iso2": company.country_iso2,
        "as_of": str(score.as_of),
        "calc_version": score.calc_version,
        "summary_version": COMPANY_SUMMARY_VERSION,
        "scores": {
            "overall": float(score.overall_score),
            "fundamental": float(score.fundamental_score),
            "market": float(score.market_score),
            "industry_context": float(score.industry_context_score),
        },
        "rank": rank,
        "rank_total": len(all_scores),
        "component_data": score.component_data or {},
        "risks": [
            {
                "type": r.risk_type,
                "severity": r.severity,
                "description": r.description,
            }
            for r in risks
        ],
        "evidence": None,
    }

    if include_evidence:
        evidence = await _build_evidence_array(db, company)
        content["evidence"] = evidence

    # Upsert packet
    as_of = score.as_of
    stmt = pg_insert(DecisionPacket).values(
        id=uuid.uuid4(),
        packet_type="company",
        entity_id=company.id,
        as_of=as_of,
        summary_version=COMPANY_SUMMARY_VERSION,
        content=content,
        score_ids=[str(score.id)],
    ).on_conflict_do_update(
        constraint="uq_packet_entity_version",
        set_={"content": content, "score_ids": [str(score.id)]},
    )
    await db.execute(stmt)

    # Fetch back
    result = await db.execute(
        select(DecisionPacket).where(
            DecisionPacket.packet_type == "company",
            DecisionPacket.entity_id == company.id,
            DecisionPacket.as_of == as_of,
            DecisionPacket.summary_version == COMPANY_SUMMARY_VERSION,
        )
    )
    return result.scalar_one()


async def _build_evidence_array(
    db: AsyncSession,
    company: Company,
) -> list[dict]:
    """Build evidence array from stored artefact references."""
    evidence = []

    query = (
        select(
            CompanySeries.series_name,
            CompanySeriesPoint.value,
            CompanySeriesPoint.date,
            CompanySeriesPoint.artefact_id,
            CompanySeries.source,
        )
        .join(CompanySeries)
        .where(CompanySeries.company_id == company.id)
        .order_by(CompanySeries.series_name, CompanySeriesPoint.date.desc())
    )
    rows = await db.execute(query)
    all_points = rows.all()

    # Take the latest point per series
    seen_series: set[str] = set()
    for row in all_points:
        if row.series_name in seen_series:
            continue
        seen_series.add(row.series_name)

        art_query = select(Artefact.source_url).where(Artefact.id == row.artefact_id)
        art_result = await db.execute(art_query)
        source_url = art_result.scalar_one_or_none() or ""

        evidence.append({
            "series": row.series_name,
            "value": float(row.value),
            "date": str(row.date),
            "artefact_id": str(row.artefact_id),
            "source": row.source,
            "source_url": source_url,
        })

    return evidence
