"""Recommendation API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.score.recommendations import compute_recommendations

router = APIRouter(prefix="/v1", tags=["recommendations"])


@router.get("/recommendations")
async def list_recommendations(
    classification: str | None = Query(None, description="Filter: Buy, Hold, or Sell"),
    country_iso2: str | None = Query(None, description="Filter by country ISO2 code"),
    gics_code: str | None = Query(None, description="Filter by GICS sector code"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return composite recommendations for all companies, sorted by composite_score desc."""
    recommendations = await compute_recommendations(db)

    if classification:
        recommendations = [r for r in recommendations if r["classification"] == classification]
    if country_iso2:
        recommendations = [r for r in recommendations if r["country_iso2"] == country_iso2]
    if gics_code:
        recommendations = [r for r in recommendations if r["gics_code"] == gics_code]

    return recommendations
