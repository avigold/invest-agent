"""Country decision packet builder."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Artefact,
    Country,
    CountryRiskRegister,
    CountryScore,
    CountrySeries,
    CountrySeriesPoint,
    DecisionPacket,
)
from app.score.versions import COUNTRY_CALC_VERSION, COUNTRY_SUMMARY_VERSION


async def build_country_packet(
    db: AsyncSession,
    country: Country,
    score: CountryScore,
    risks: list[CountryRiskRegister],
    all_scores: list[CountryScore],
    include_evidence: bool = False,
) -> DecisionPacket:
    """Build a decision packet from stored scores and evidence.

    Assembled strictly from stored data — no invented narrative.
    """
    # Compute rank among all countries (1 = best)
    sorted_scores = sorted(all_scores, key=lambda s: float(s.overall_score), reverse=True)
    rank = 1
    for i, s in enumerate(sorted_scores):
        if s.country_id == country.id:
            rank = i + 1
            break

    content: dict = {
        "iso2": country.iso2,
        "country_name": country.name,
        "as_of": str(score.as_of),
        "calc_version": score.calc_version,
        "summary_version": COUNTRY_SUMMARY_VERSION,
        "scores": {
            "overall": float(score.overall_score),
            "macro": float(score.macro_score),
            "market": float(score.market_score),
            "stability": float(score.stability_score),
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
        evidence = await _build_evidence_array(db, country, score)
        content["evidence"] = evidence

    # Upsert packet
    as_of = score.as_of
    stmt = pg_insert(DecisionPacket).values(
        id=uuid.uuid4(),
        packet_type="country",
        entity_id=country.id,
        as_of=as_of,
        summary_version=COUNTRY_SUMMARY_VERSION,
        content=content,
        score_ids=[str(score.id)],
    ).on_conflict_do_update(
        constraint="uq_packet_entity_version",
        set_={"content": content, "score_ids": [str(score.id)]},
    )
    await db.execute(stmt)

    # Fetch the packet back
    result = await db.execute(
        select(DecisionPacket).where(
            DecisionPacket.packet_type == "country",
            DecisionPacket.entity_id == country.id,
            DecisionPacket.as_of == as_of,
            DecisionPacket.summary_version == COUNTRY_SUMMARY_VERSION,
        )
    )
    return result.scalar_one()


async def _build_evidence_array(
    db: AsyncSession,
    country: Country,
    score: CountryScore,
) -> list[dict]:
    """Build evidence array from stored artefact references."""
    evidence = []

    # Get all series points for this country that were used in scoring
    query = (
        select(
            CountrySeries.series_name,
            CountrySeriesPoint.value,
            CountrySeriesPoint.date,
            CountrySeriesPoint.artefact_id,
            CountrySeries.source,
        )
        .join(CountrySeries)
        .where(CountrySeries.country_id == country.id)
        .order_by(CountrySeries.series_name, CountrySeriesPoint.date.desc())
    )
    rows = await db.execute(query)
    all_points = rows.all()

    # Group by series and take the latest point for each
    seen_series: set[str] = set()
    for row in all_points:
        if row.series_name in seen_series:
            continue
        seen_series.add(row.series_name)

        # Get artefact source_url
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
