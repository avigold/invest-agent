"""Industry decision packet builder."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Country,
    DecisionPacket,
    Industry,
    IndustryRiskRegister,
    IndustryScore,
)
from app.score.versions import INDUSTRY_CALC_VERSION, INDUSTRY_SUMMARY_VERSION


async def build_industry_packet(
    db: AsyncSession,
    industry: Industry,
    country: Country,
    score: IndustryScore,
    risks: list[IndustryRiskRegister],
    all_scores: list[IndustryScore],
) -> DecisionPacket:
    """Build a decision packet for an industry×country combination.

    Assembled strictly from stored data.
    """
    # Compute rank among all 110 combinations (1 = best)
    sorted_scores = sorted(all_scores, key=lambda s: float(s.overall_score), reverse=True)
    rank = 1
    for i, s in enumerate(sorted_scores):
        if s.industry_id == industry.id and s.country_id == country.id:
            rank = i + 1
            break

    # Use a composite entity_id: XOR of industry.id and country.id for uniqueness
    entity_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{industry.id}:{country.id}")

    content: dict = {
        "gics_code": industry.gics_code,
        "industry_name": industry.name,
        "country_iso2": country.iso2,
        "country_name": country.name,
        "as_of": str(score.as_of),
        "calc_version": score.calc_version,
        "summary_version": INDUSTRY_SUMMARY_VERSION,
        "scores": {
            "overall": float(score.overall_score),
            "rubric": float(score.rubric_score),
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

    # Upsert packet
    as_of = score.as_of
    stmt = pg_insert(DecisionPacket).values(
        id=uuid.uuid4(),
        packet_type="industry",
        entity_id=entity_id,
        as_of=as_of,
        summary_version=INDUSTRY_SUMMARY_VERSION,
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
            DecisionPacket.packet_type == "industry",
            DecisionPacket.entity_id == entity_id,
            DecisionPacket.as_of == as_of,
            DecisionPacket.summary_version == INDUSTRY_SUMMARY_VERSION,
        )
    )
    return result.scalar_one()
