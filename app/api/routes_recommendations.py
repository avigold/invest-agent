"""Recommendation API endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.recommendation_analysis import (
    compute_score_hash,
    get_cached_analysis,
)
from app.api.deps import get_current_user
from app.db.models import (
    Company,
    Country,
    DecisionPacket,
    Industry,
    ScoringProfile,
    User,
)
from app.db.session import get_db
from app.score.profile_rescore import load_score_component_data, rescore_recommendations
from app.score.profile_schema import ScoringProfileConfig
from app.score.recommendations import compute_recommendations
from app.score.versions import (
    COMPANY_SUMMARY_VERSION,
    COUNTRY_SUMMARY_VERSION,
    INDUSTRY_SUMMARY_VERSION,
    RECOMMENDATION_WEIGHTS,
)

router = APIRouter(prefix="/v1", tags=["recommendations"])


@router.get("/recommendations")
async def list_recommendations(
    classification: str | None = Query(None, description="Filter: Buy, Hold, or Sell"),
    country_iso2: str | None = Query(None, description="Filter by country ISO2 code"),
    gics_code: str | None = Query(None, description="Filter by GICS sector code"),
    profile_id: uuid.UUID | None = Query(None, description="Scoring profile ID for custom rescoring"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return composite recommendations for all companies, sorted by composite_score desc."""
    recommendations = await compute_recommendations(db)

    # Resolve scoring profile
    profile, profile_name = await _resolve_profile(db, user.id, profile_id)

    if profile:
        component_bundles = await load_score_component_data(db)
        recommendations = rescore_recommendations(recommendations, component_bundles, profile)

    if classification:
        recommendations = [r for r in recommendations if r["classification"] == classification]
    if country_iso2:
        recommendations = [r for r in recommendations if r["country_iso2"] == country_iso2]
    if gics_code:
        recommendations = [r for r in recommendations if r["gics_code"] == gics_code]

    # Add profile metadata
    for rec in recommendations:
        rec["profile_id"] = str(profile_id) if profile_id else None
        rec["profile_name"] = profile_name
        rec["is_custom_profile"] = profile is not None

    return recommendations


@router.get("/recommendation/{ticker}")
async def recommendation_detail(
    ticker: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return full recommendation detail for a single company.

    Analysis is returned from cache only — trigger generation via the
    recommendation_analysis job command.
    """
    ticker = ticker.upper()

    # Compute all recommendations and find this ticker
    recommendations = await compute_recommendations(db)
    rec = next((r for r in recommendations if r["ticker"] == ticker), None)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"No recommendation found for '{ticker}'")

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

    if industry and country:
        industry_entity_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{industry.id}:{country.id}")
        pkt = await _latest_packet(db, "industry", industry_entity_id, INDUSTRY_SUMMARY_VERSION)
        packets["industry"] = pkt.content if pkt else None

    if company:
        pkt = await _latest_packet(db, "company", company.id, COMPANY_SUMMARY_VERSION)
        packets["company"] = pkt.content if pkt else None

    # Compute score hash and check for cached analysis
    score_hash = compute_score_hash(rec, packets)
    analysis = await get_cached_analysis(db, ticker, score_hash)

    return {
        "ticker": rec["ticker"],
        "name": rec["name"],
        "classification": rec["classification"],
        "composite_score": rec["composite_score"],
        "rank": rec["rank"],
        "rank_total": rec["rank_total"],
        "as_of": rec["as_of"],
        "recommendation_version": rec["recommendation_version"],
        "scores": {
            "company": {"score": rec["company_score"], "weight": RECOMMENDATION_WEIGHTS["company"]},
            "country": {"score": rec["country_score"], "weight": RECOMMENDATION_WEIGHTS["country"]},
            "industry": {"score": rec["industry_score"], "weight": RECOMMENDATION_WEIGHTS["industry"]},
        },
        "country": {
            "iso2": rec["country_iso2"],
            "name": country.name if country else rec["country_iso2"],
            "overall_score": rec["country_score"],
        },
        "industry": {
            "gics_code": rec["gics_code"],
            "name": industry.name if industry else rec["gics_code"],
            "country_iso2": rec["country_iso2"],
            "overall_score": rec["industry_score"],
        },
        "company": {
            "ticker": rec["ticker"],
            "name": rec["name"],
            "overall_score": rec["company_score"],
        },
        "analysis": analysis,
    }


async def _latest_packet(
    db: AsyncSession, packet_type: str, entity_id, summary_version: str
) -> DecisionPacket | None:
    """Fetch the latest decision packet for an entity."""
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


async def _resolve_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile_id: uuid.UUID | None,
) -> tuple[ScoringProfileConfig | None, str | None]:
    """Resolve a scoring profile for the user.

    Returns (config, name) or (None, None) if using system defaults.
    """
    if profile_id:
        result = await db.execute(
            select(ScoringProfile).where(ScoringProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None or profile.user_id != user_id:
            return None, None
        return ScoringProfileConfig(**profile.config), profile.name

    # Check for user's default profile
    result = await db.execute(
        select(ScoringProfile).where(
            ScoringProfile.user_id == user_id,
            ScoringProfile.is_default == True,  # noqa: E712
        )
    )
    profile = result.scalar_one_or_none()
    if profile:
        return ScoringProfileConfig(**profile.config), profile.name

    return None, None
