"""Company API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Company,
    CompanyScore,
    DecisionPacket,
    User,
)
from app.db.session import get_db
from app.score.versions import COMPANY_CALC_VERSION, COMPANY_SUMMARY_VERSION

router = APIRouter(prefix="/v1", tags=["companies"])


@router.get("/companies")
async def list_companies(
    gics_code: str | None = Query(None, description="Filter by GICS sector code"),
    country_iso2: str | None = Query(None, description="Filter by country ISO2 code"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return latest scores for all companies, sorted by overall score desc."""
    latest_date_q = (
        select(CompanyScore.as_of)
        .where(CompanyScore.calc_version == COMPANY_CALC_VERSION)
        .order_by(desc(CompanyScore.as_of))
        .limit(1)
    )
    result = await db.execute(latest_date_q)
    latest_date = result.scalar_one_or_none()
    if latest_date is None:
        return []

    scores_q = (
        select(CompanyScore, Company)
        .join(Company, CompanyScore.company_id == Company.id)
        .where(
            CompanyScore.as_of == latest_date,
            CompanyScore.calc_version == COMPANY_CALC_VERSION,
        )
    )
    if gics_code:
        scores_q = scores_q.where(Company.gics_code == gics_code)
    if country_iso2:
        scores_q = scores_q.where(Company.country_iso2 == country_iso2)
    scores_q = scores_q.order_by(desc(CompanyScore.overall_score))

    result = await db.execute(scores_q)
    rows = result.all()

    items = []
    for rank, (score, company) in enumerate(rows, 1):
        items.append({
            "ticker": company.ticker,
            "name": company.name,
            "gics_code": company.gics_code,
            "country_iso2": company.country_iso2,
            "overall_score": float(score.overall_score),
            "fundamental_score": float(score.fundamental_score),
            "market_score": float(score.market_score),
            "industry_context_score": float(score.industry_context_score),
            "rank": rank,
            "rank_total": len(rows),
            "as_of": str(score.as_of),
            "calc_version": score.calc_version,
        })
    return items


@router.get("/company/{ticker}/summary")
async def company_summary(
    ticker: str,
    as_of: str | None = Query(None, description="Date in YYYY-MM-DD format"),
    include_evidence: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full decision packet for a single company."""
    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Company '{ticker}' not found")

    query = (
        select(DecisionPacket)
        .where(
            DecisionPacket.packet_type == "company",
            DecisionPacket.entity_id == company.id,
            DecisionPacket.summary_version == COMPANY_SUMMARY_VERSION,
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
        raise HTTPException(
            status_code=404,
            detail=f"No decision packet found for {ticker}",
        )

    content = dict(packet.content)
    if not include_evidence:
        content["evidence"] = None
    return content
