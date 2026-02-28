"""Country API endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Country,
    CountryScore,
    DecisionPacket,
    User,
)
from app.db.session import get_db
from app.score.versions import COUNTRY_CALC_VERSION, COUNTRY_SUMMARY_VERSION

router = APIRouter(prefix="/v1", tags=["countries"])


@router.get("/countries")
async def list_countries(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return latest scores for all investable countries, sorted by overall score desc."""
    # Find the most recent as_of date
    latest_date_q = (
        select(CountryScore.as_of)
        .where(CountryScore.calc_version == COUNTRY_CALC_VERSION)
        .order_by(desc(CountryScore.as_of))
        .limit(1)
    )
    result = await db.execute(latest_date_q)
    latest_date = result.scalar_one_or_none()

    if latest_date is None:
        return []

    # Get all scores for that date
    scores_q = (
        select(CountryScore, Country)
        .join(Country, CountryScore.country_id == Country.id)
        .where(
            CountryScore.as_of == latest_date,
            CountryScore.calc_version == COUNTRY_CALC_VERSION,
        )
        .order_by(desc(CountryScore.overall_score))
    )
    result = await db.execute(scores_q)
    rows = result.all()

    items = []
    for rank, (score, country) in enumerate(rows, 1):
        items.append({
            "iso2": country.iso2,
            "name": country.name,
            "overall_score": float(score.overall_score),
            "macro_score": float(score.macro_score),
            "market_score": float(score.market_score),
            "stability_score": float(score.stability_score),
            "rank": rank,
            "as_of": str(score.as_of),
            "calc_version": score.calc_version,
        })

    return items


@router.get("/country/{iso2}/summary")
async def country_summary(
    iso2: str,
    as_of: str | None = Query(None, description="Date in YYYY-MM-DD format, defaults to latest"),
    include_evidence: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full decision packet for a single country."""
    # Validate country exists
    result = await db.execute(select(Country).where(Country.iso2 == iso2.upper()))
    country = result.scalar_one_or_none()
    if country is None:
        raise HTTPException(status_code=404, detail=f"Country '{iso2}' not found")

    # Find packet
    query = (
        select(DecisionPacket)
        .where(
            DecisionPacket.packet_type == "country",
            DecisionPacket.entity_id == country.id,
            DecisionPacket.summary_version == COUNTRY_SUMMARY_VERSION,
        )
    )

    if as_of:
        query = query.where(DecisionPacket.as_of == as_of)
    else:
        query = query.order_by(desc(DecisionPacket.as_of))

    query = query.limit(1)
    result = await db.execute(query)
    packet = result.scalar_one_or_none()

    if packet is None:
        raise HTTPException(status_code=404, detail=f"No decision packet found for {iso2}")

    content = dict(packet.content)

    # Strip evidence if not requested
    if not include_evidence:
        content["evidence"] = None

    return content
