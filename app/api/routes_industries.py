"""Industry API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Country,
    DecisionPacket,
    Industry,
    IndustryScore,
    User,
)
from app.db.session import get_db
from app.score.versions import INDUSTRY_CALC_VERSION, INDUSTRY_SUMMARY_VERSION

router = APIRouter(prefix="/v1", tags=["industries"])


@router.get("/industries")
async def list_industries(
    iso2: str | None = Query(None, description="Filter by country ISO2 code"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return latest scores for all industry×country combinations."""
    # Find the most recent as_of date
    latest_date_q = (
        select(IndustryScore.as_of)
        .where(IndustryScore.calc_version == INDUSTRY_CALC_VERSION)
        .order_by(desc(IndustryScore.as_of))
        .limit(1)
    )
    result = await db.execute(latest_date_q)
    latest_date = result.scalar_one_or_none()

    if latest_date is None:
        return []

    # Get all scores for that date
    scores_q = (
        select(IndustryScore, Industry, Country)
        .join(Industry, IndustryScore.industry_id == Industry.id)
        .join(Country, IndustryScore.country_id == Country.id)
        .where(
            IndustryScore.as_of == latest_date,
            IndustryScore.calc_version == INDUSTRY_CALC_VERSION,
        )
    )

    if iso2:
        scores_q = scores_q.where(Country.iso2 == iso2.upper())

    scores_q = scores_q.order_by(desc(IndustryScore.overall_score))

    result = await db.execute(scores_q)
    rows = result.all()

    items = []
    for rank, (score, industry, country) in enumerate(rows, 1):
        items.append({
            "gics_code": industry.gics_code,
            "industry_name": industry.name,
            "country_iso2": country.iso2,
            "country_name": country.name,
            "overall_score": float(score.overall_score),
            "rubric_score": float(score.rubric_score),
            "rank": rank,
            "as_of": str(score.as_of),
            "calc_version": score.calc_version,
        })

    return items


@router.get("/industry/{gics_code}/summary")
async def industry_summary(
    gics_code: str,
    iso2: str = Query(..., description="Country ISO2 code (required)"),
    include_evidence: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full decision packet for a single industry×country combination."""
    import uuid as uuid_mod

    # Validate industry exists
    result = await db.execute(select(Industry).where(Industry.gics_code == gics_code))
    industry = result.scalar_one_or_none()
    if industry is None:
        raise HTTPException(status_code=404, detail=f"Industry with GICS code '{gics_code}' not found")

    # Validate country exists
    result = await db.execute(select(Country).where(Country.iso2 == iso2.upper()))
    country = result.scalar_one_or_none()
    if country is None:
        raise HTTPException(status_code=404, detail=f"Country '{iso2}' not found")

    # Compute entity_id (same logic as packet builder)
    entity_id = uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, f"{industry.id}:{country.id}")

    # Find packet
    query = (
        select(DecisionPacket)
        .where(
            DecisionPacket.packet_type == "industry",
            DecisionPacket.entity_id == entity_id,
            DecisionPacket.summary_version == INDUSTRY_SUMMARY_VERSION,
        )
        .order_by(desc(DecisionPacket.as_of))
        .limit(1)
    )
    result = await db.execute(query)
    packet = result.scalar_one_or_none()

    if packet is None:
        raise HTTPException(
            status_code=404,
            detail=f"No decision packet found for {industry.name} in {iso2}",
        )

    content = dict(packet.content)

    if not include_evidence:
        content["evidence"] = None

    return content
