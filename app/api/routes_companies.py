"""Company API endpoints."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Company,
    CompanyPriceHistory,
    CompanyScore,
    CompanySeries,
    CompanySeriesPoint,
    DecisionPacket,
    User,
)
from app.db.session import get_db
from app.ingest.fmp import fetch_historical_prices
from app.score.versions import COMPANY_CALC_VERSION, COMPANY_SUMMARY_VERSION
from app.utils.market_hours import get_market_status

_COUNTRY_CURRENCIES: dict[str, str] = {
    "US": "USD", "CA": "CAD", "GB": "GBP", "AU": "AUD", "NZ": "NZD",
    "JP": "JPY", "KR": "KRW", "BR": "BRL", "ZA": "ZAR", "SG": "SGD",
    "HK": "HKD", "TW": "TWD", "IL": "ILS", "NO": "NOK", "SE": "SEK",
    "DK": "DKK", "CH": "CHF",
    # Eurozone
    "DE": "EUR", "FR": "EUR", "NL": "EUR", "FI": "EUR",
    "IE": "EUR", "BE": "EUR", "AT": "EUR",
}


def _country_currency(iso2: str | None) -> str:
    return _COUNTRY_CURRENCIES.get(iso2 or "", "USD")


router = APIRouter(prefix="/v1", tags=["companies"])


@router.get("/companies")
async def list_companies(
    gics_code: str | None = Query(None, description="Filter by GICS sector code"),
    country_iso2: str | None = Query(None, description="Filter by country ISO2 code"),
    limit: int | None = Query(None, ge=1, description="Max results to return"),
    offset: int | None = Query(None, ge=0, description="Results to skip"),
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

    # Get scored_at from the most recent packet for this date
    scored_at_q = (
        select(DecisionPacket.created_at)
        .where(
            DecisionPacket.packet_type == "company",
            DecisionPacket.as_of == latest_date,
            DecisionPacket.summary_version == COMPANY_SUMMARY_VERSION,
        )
        .order_by(desc(DecisionPacket.created_at))
        .limit(1)
    )
    scored_at_result = await db.execute(scored_at_q)
    scored_at = scored_at_result.scalar_one_or_none()

    base_q = (
        select(CompanyScore, Company)
        .join(Company, CompanyScore.company_id == Company.id)
        .where(
            CompanyScore.as_of == latest_date,
            CompanyScore.calc_version == COMPANY_CALC_VERSION,
        )
    )
    if gics_code:
        base_q = base_q.where(Company.gics_code == gics_code)
    if country_iso2:
        base_q = base_q.where(Company.country_iso2 == country_iso2)
    base_q = base_q.order_by(desc(CompanyScore.overall_score))

    # Total count (needed when limit is used)
    if limit is not None:
        from sqlalchemy import func
        count_q = select(func.count()).select_from(base_q.subquery())
        total = (await db.execute(count_q)).scalar() or 0
    else:
        total = None  # computed from len(rows) below

    scores_q = base_q
    if offset:
        scores_q = scores_q.offset(offset)
    if limit is not None:
        scores_q = scores_q.limit(limit)

    result = await db.execute(scores_q)
    rows = result.all()

    if total is None:
        total = len(rows)

    rank_start = (offset or 0) + 1
    items = []
    for i, (score, company) in enumerate(rows):
        items.append({
            "ticker": company.ticker,
            "name": company.name,
            "gics_code": company.gics_code,
            "country_iso2": company.country_iso2,
            "overall_score": float(score.overall_score),
            "fundamental_score": float(score.fundamental_score),
            "market_score": float(score.market_score),
            "industry_context_score": float(score.industry_context_score),
            "rank": rank_start + i,
            "rank_total": total,
            "as_of": str(score.as_of),
            "scored_at": scored_at.isoformat() if scored_at else None,
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
    ticker = ticker.replace("-", ".")
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

    if packet is not None:
        content = dict(packet.content)
        if not include_evidence:
            content["evidence"] = None
        return content

    # Fallback: build response from CompanyScore when no DecisionPacket exists
    score_q = (
        select(CompanyScore)
        .where(
            CompanyScore.company_id == company.id,
            CompanyScore.calc_version == COMPANY_CALC_VERSION,
        )
        .order_by(desc(CompanyScore.as_of))
        .limit(1)
    )
    score_result = await db.execute(score_q)
    score = score_result.scalar_one_or_none()
    if score is None:
        raise HTTPException(
            status_code=404,
            detail=f"No data found for {ticker}",
        )

    # Count total scored companies for rank_total
    from sqlalchemy import func as sa_func
    count_q = select(sa_func.count()).select_from(CompanyScore).where(
        CompanyScore.as_of == score.as_of,
        CompanyScore.calc_version == COMPANY_CALC_VERSION,
    )
    total = (await db.execute(count_q)).scalar() or 0

    # Compute rank (how many have higher overall_score)
    rank_q = select(sa_func.count()).select_from(CompanyScore).where(
        CompanyScore.as_of == score.as_of,
        CompanyScore.calc_version == COMPANY_CALC_VERSION,
        CompanyScore.overall_score > score.overall_score,
    )
    rank = ((await db.execute(rank_q)).scalar() or 0) + 1

    return {
        "ticker": company.ticker,
        "cik": getattr(company, "cik", None) or "",
        "company_name": company.name,
        "gics_code": company.gics_code,
        "country_iso2": company.country_iso2,
        "as_of": str(score.as_of),
        "calc_version": score.calc_version,
        "summary_version": "score_fallback",
        "scores": {
            "overall": float(score.overall_score),
            "fundamental": float(score.fundamental_score),
            "market": float(score.market_score),
        },
        "rank": rank,
        "rank_total": total,
        "component_data": score.component_data or {},
        "risks": [],
        "evidence": None,
    }


PERIOD_DAYS = {
    "1w": 7,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "5y": 1825,
}


async def _fmp_chart_fallback(ticker: str, period: str) -> JSONResponse:
    """Fetch chart data from FMP for tickers not in the Company DB."""
    import os
    import httpx

    api_key = os.environ.get("FMP_API_KEY")
    start_date = date.today() - timedelta(days=PERIOD_DAYS[period])
    points_list: list[dict] = []

    if api_key:
        try:
            async with httpx.AsyncClient() as client:
                rows, _ = await fetch_historical_prices(
                    client, ticker, api_key, from_date=str(start_date),
                )
            points_list = [
                {"date": r["date"], "value": float(r["price"])}
                for r in rows if r.get("price") is not None
            ]
        except Exception:
            pass  # Return empty points on failure

    latest = None
    if len(points_list) >= 2:
        last, prev = points_list[-1], points_list[-2]
        change = last["value"] - prev["value"]
        pct = change / prev["value"] if prev["value"] != 0 else 0
        latest = {
            "date": last["date"], "value": last["value"],
            "change_1d": round(change, 4), "change_1d_pct": round(pct, 6),
            "prev_close": prev["value"],
        }
    elif len(points_list) == 1:
        last = points_list[0]
        latest = {
            "date": last["date"], "value": last["value"],
            "change_1d": 0, "change_1d_pct": 0, "prev_close": last["value"],
        }

    return JSONResponse(
        content={
            "ticker": ticker, "currency": "USD", "period": period,
            "points": points_list, "latest": latest,
            "market_status": {"is_open": False, "exchange": "", "next_open": "", "last_close_time": ""},
        },
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.get("/company/{ticker}/chart")
async def company_chart(
    ticker: str,
    period: str = Query("1y", description="Time period: 1w, 1m, 3m, 6m, 1y, 5y"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return historical price data for charting."""
    ticker = ticker.replace("-", ".")
    if period not in PERIOD_DAYS:
        raise HTTPException(status_code=400, detail=f"Invalid period '{period}'. Must be one of: {', '.join(PERIOD_DAYS)}")

    result = await db.execute(
        select(Company).where(Company.ticker == ticker.upper())
    )
    company = result.scalar_one_or_none()
    if company is None:
        return await _fmp_chart_fallback(ticker.upper(), period)

    start_date = date.today() - timedelta(days=PERIOD_DAYS[period])
    start_str = str(start_date)

    # Try JSONB price history first (fast path)
    result = await db.execute(
        select(CompanyPriceHistory).where(
            CompanyPriceHistory.company_id == company.id,
        )
    )
    ph = result.scalar_one_or_none()

    points_list: list[dict] = []
    if ph and ph.prices:
        for p in ph.prices:
            if p["date"] >= start_str:
                price_val = p.get("price") or p.get("close")
                if price_val is not None:
                    points_list.append({"date": p["date"], "value": float(price_val)})
    else:
        # Fallback to legacy CompanySeries/CompanySeriesPoint
        result = await db.execute(
            select(CompanySeries).where(
                CompanySeries.company_id == company.id,
                CompanySeries.series_name == "equity_close",
            )
        )
        series = result.scalar_one_or_none()
        if series is not None:
            result = await db.execute(
                select(CompanySeriesPoint)
                .where(
                    CompanySeriesPoint.series_id == series.id,
                    CompanySeriesPoint.date >= start_date,
                )
                .order_by(CompanySeriesPoint.date.asc())
            )
            points_list = [{"date": str(p.date), "value": float(p.value)} for p in result.scalars().all()]

    # Compute latest change
    latest = None
    if len(points_list) >= 2:
        last = points_list[-1]
        prev = points_list[-2]
        change = last["value"] - prev["value"]
        pct = change / prev["value"] if prev["value"] != 0 else 0
        latest = {
            "date": last["date"],
            "value": last["value"],
            "change_1d": round(change, 4),
            "change_1d_pct": round(pct, 6),
            "prev_close": prev["value"],
        }
    elif len(points_list) == 1:
        last = points_list[0]
        latest = {
            "date": last["date"],
            "value": last["value"],
            "change_1d": 0,
            "change_1d_pct": 0,
            "prev_close": last["value"],
        }

    market_status = get_market_status(company.country_iso2)
    cache_max_age = 30 if market_status["is_open"] else 3600

    return JSONResponse(
        content={
            "ticker": company.ticker,
            "currency": _country_currency(company.country_iso2),
            "period": period,
            "points": points_list,
            "latest": latest,
            "market_status": market_status,
        },
        headers={"Cache-Control": f"private, max-age={cache_max_age}"},
    )
