"""Watchlist API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import (
    Company,
    CompanyPriceHistory,
    CompanyScore,
    Country,
    CountryScore,
    Industry,
    IndustryScore,
    User,
    WatchlistItem,
)
from app.db.session import get_db
from app.score.versions import (
    COMPANY_CALC_VERSION,
    COUNTRY_CALC_VERSION,
    INDUSTRY_CALC_VERSION,
    RECOMMENDATION_WEIGHTS,
)

router = APIRouter(prefix="/v1/watchlist", tags=["watchlist"])

_MAX_WATCHLIST_SIZE = 200

_COUNTRY_CURRENCIES: dict[str, str] = {
    "US": "USD", "CA": "CAD", "GB": "GBP", "AU": "AUD", "NZ": "NZD",
    "JP": "JPY", "KR": "KRW", "BR": "BRL", "ZA": "ZAR", "SG": "SGD",
    "HK": "HKD", "TW": "TWD", "IL": "ILS", "NO": "NOK", "SE": "SEK",
    "DK": "DKK", "CH": "CHF",
    "DE": "EUR", "FR": "EUR", "NL": "EUR", "FI": "EUR",
    "IE": "EUR", "BE": "EUR", "AT": "EUR",
}


def _currency(iso2: str | None) -> str:
    return _COUNTRY_CURRENCIES.get(iso2 or "", "USD")


def _extract_latest_prices(prices_json: list | None) -> dict:
    """Extract latest price and 1-day change from JSONB price array."""
    if not prices_json or len(prices_json) == 0:
        return {"latest_price": None, "change_1d": None, "change_1d_pct": None, "price_date": None}

    latest = prices_json[-1]
    price = latest.get("price")
    date = latest.get("date")

    if len(prices_json) >= 2:
        prev = prices_json[-2]
        prev_price = prev.get("price")
        if price is not None and prev_price is not None and prev_price != 0:
            change = price - prev_price
            change_pct = change / prev_price
            return {"latest_price": price, "change_1d": round(change, 4), "change_1d_pct": round(change_pct, 4), "price_date": date}

    return {"latest_price": price, "change_1d": None, "change_1d_pct": None, "price_date": date}


@router.get("")
async def list_watchlist(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return user's watchlist with enriched price and score data."""
    # Load watchlist items with company and price data
    result = await db.execute(
        select(WatchlistItem, Company, CompanyPriceHistory)
        .join(Company, WatchlistItem.company_id == Company.id)
        .outerjoin(CompanyPriceHistory, CompanyPriceHistory.company_id == Company.id)
        .where(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.position)
    )
    rows = result.all()

    if not rows:
        return []

    # Collect company IDs for score lookup
    company_ids = [wi.company_id for wi, _, _ in rows]

    # Load latest company scores for these companies
    latest_score_sq = (
        select(
            CompanyScore.company_id,
            func.max(CompanyScore.as_of).label("max_as_of"),
        )
        .where(
            CompanyScore.calc_version == COMPANY_CALC_VERSION,
            CompanyScore.company_id.in_(company_ids),
        )
        .group_by(CompanyScore.company_id)
        .subquery()
    )
    score_result = await db.execute(
        select(CompanyScore)
        .join(
            latest_score_sq,
            (CompanyScore.company_id == latest_score_sq.c.company_id)
            & (CompanyScore.as_of == latest_score_sq.c.max_as_of),
        )
        .where(CompanyScore.calc_version == COMPANY_CALC_VERSION)
    )
    scores_by_company: dict = {s.company_id: s for s in score_result.scalars().all()}

    # Load country scores
    country_scores: dict[str, float] = {}
    cs_sq = (
        select(CountryScore.country_id, func.max(CountryScore.as_of).label("max_as_of"))
        .where(CountryScore.calc_version == COUNTRY_CALC_VERSION)
        .group_by(CountryScore.country_id)
        .subquery()
    )
    cs_result = await db.execute(
        select(Country.iso2, CountryScore.overall_score)
        .join(CountryScore, CountryScore.country_id == Country.id)
        .join(cs_sq, (CountryScore.country_id == cs_sq.c.country_id)
              & (CountryScore.as_of == cs_sq.c.max_as_of))
        .where(CountryScore.calc_version == COUNTRY_CALC_VERSION)
    )
    for iso2, val in cs_result.all():
        country_scores[iso2] = float(val)

    # Load industry scores
    industry_scores: dict[tuple[str, str], float] = {}
    is_sq = (
        select(IndustryScore.industry_id, IndustryScore.country_id,
               func.max(IndustryScore.as_of).label("max_as_of"))
        .where(IndustryScore.calc_version == INDUSTRY_CALC_VERSION)
        .group_by(IndustryScore.industry_id, IndustryScore.country_id)
        .subquery()
    )
    is_result = await db.execute(
        select(Industry.gics_code, Country.iso2, IndustryScore.overall_score)
        .join(IndustryScore, IndustryScore.industry_id == Industry.id)
        .join(Country, IndustryScore.country_id == Country.id)
        .join(is_sq, (IndustryScore.industry_id == is_sq.c.industry_id)
              & (IndustryScore.country_id == is_sq.c.country_id)
              & (IndustryScore.as_of == is_sq.c.max_as_of))
        .where(IndustryScore.calc_version == INDUSTRY_CALC_VERSION)
    )
    for gics, iso2, val in is_result.all():
        industry_scores[(gics, iso2)] = float(val)

    # Build response
    w = RECOMMENDATION_WEIGHTS
    items = []
    for wi, company, price_hist in rows:
        price_data = _extract_latest_prices(price_hist.prices if price_hist else None)

        cs = scores_by_company.get(company.id)
        overall = float(cs.overall_score) if cs else None
        fundamental = float(cs.fundamental_score) if cs else None
        market = float(cs.market_score) if cs else None

        cs_val = country_scores.get(company.country_iso2, 10.0)
        ind_val = industry_scores.get((company.gics_code, company.country_iso2), 10.0)
        composite = round(w["country"] * cs_val + w["industry"] * ind_val + w["company"] * (overall or 0), 2) if overall is not None else None

        items.append({
            "id": str(wi.id),
            "ticker": wi.ticker,
            "name": company.name,
            "country_iso2": company.country_iso2,
            "gics_code": company.gics_code,
            "position": wi.position,
            "added_at": wi.added_at.isoformat(),
            "currency": _currency(company.country_iso2),
            "overall_score": overall,
            "composite_score": composite,
            "fundamental_score": fundamental,
            "market_score": market,
            **price_data,
        })

    return items


class _AddTicker(BaseModel):
    ticker: str


class _BulkAddTickers(BaseModel):
    tickers: list[str]


@router.post("", status_code=201)
async def add_to_watchlist(
    body: _AddTicker,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a ticker to the user's watchlist."""
    ticker = body.ticker.strip().upper()

    # Look up company
    result = await db.execute(select(Company).where(Company.ticker == ticker))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Company '{ticker}' not found")

    # Check duplicate
    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.company_id == company.id,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"'{ticker}' is already in your watchlist")

    # Check size limit
    result = await db.execute(
        select(func.count()).where(WatchlistItem.user_id == user.id)
    )
    count = result.scalar() or 0
    if count >= _MAX_WATCHLIST_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Watchlist is full ({_MAX_WATCHLIST_SIZE} items max)",
        )

    # Compute next position
    result = await db.execute(
        select(func.coalesce(func.max(WatchlistItem.position), -1)).where(
            WatchlistItem.user_id == user.id
        )
    )
    next_pos = (result.scalar() or -1) + 1

    item = WatchlistItem(
        user_id=user.id,
        company_id=company.id,
        ticker=company.ticker,
        position=next_pos,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return {"id": str(item.id), "ticker": item.ticker, "position": item.position}


@router.post("/bulk")
async def bulk_add_to_watchlist(
    body: _BulkAddTickers,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-add tickers to watchlist, skipping duplicates and unknowns."""
    tickers = list(dict.fromkeys(t.strip().upper() for t in body.tickers if t.strip()))
    if not tickers:
        return {"added": 0, "skipped": 0, "tickers_added": []}

    # Look up companies
    result = await db.execute(
        select(Company).where(Company.ticker.in_(tickers))
    )
    companies_by_ticker = {c.ticker: c for c in result.scalars().all()}

    # Load existing watchlist company_ids
    result = await db.execute(
        select(WatchlistItem.company_id).where(WatchlistItem.user_id == user.id)
    )
    existing_ids = {row for row in result.scalars().all()}

    # Current count for capacity check
    current_count = len(existing_ids)

    # Get max position
    result = await db.execute(
        select(func.coalesce(func.max(WatchlistItem.position), -1)).where(
            WatchlistItem.user_id == user.id
        )
    )
    next_pos = (result.scalar() or -1) + 1

    added_tickers = []
    skipped = 0
    for ticker in tickers:
        company = companies_by_ticker.get(ticker)
        if company is None:
            skipped += 1
            continue
        if company.id in existing_ids:
            skipped += 1
            continue
        if current_count >= _MAX_WATCHLIST_SIZE:
            skipped += len(tickers) - len(added_tickers) - skipped
            break

        item = WatchlistItem(
            user_id=user.id,
            company_id=company.id,
            ticker=company.ticker,
            position=next_pos,
        )
        db.add(item)
        existing_ids.add(company.id)
        added_tickers.append(company.ticker)
        next_pos += 1
        current_count += 1

    if added_tickers:
        await db.commit()

    return {
        "added": len(added_tickers),
        "skipped": skipped,
        "tickers_added": added_tickers,
    }


@router.delete("/{ticker}", status_code=204)
async def remove_from_watchlist(
    ticker: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a ticker from the user's watchlist."""
    ticker = ticker.strip().upper()
    result = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.ticker == ticker,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail=f"'{ticker}' is not in your watchlist")

    await db.delete(item)
    await db.commit()


@router.get("/check/{ticker}")
async def check_watchlist(
    ticker: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if a ticker is in the user's watchlist."""
    ticker = ticker.strip().upper()
    result = await db.execute(
        select(WatchlistItem.id).where(
            WatchlistItem.user_id == user.id,
            WatchlistItem.ticker == ticker,
        )
    )
    row = result.scalar_one_or_none()
    return {"in_watchlist": row is not None}


class _ReorderBody(BaseModel):
    order: list[str]


@router.put("/reorder")
async def reorder_watchlist(
    body: _ReorderBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reorder watchlist items. Body contains ordered list of item UUIDs."""
    import uuid

    # Load all user's items
    result = await db.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == user.id)
    )
    items_by_id = {str(item.id): item for item in result.scalars().all()}

    # Validate
    order_set = set(body.order)
    items_set = set(items_by_id.keys())
    if order_set != items_set:
        raise HTTPException(
            status_code=422,
            detail="Order must contain exactly all watchlist item IDs",
        )

    # Update positions
    for i, item_id in enumerate(body.order):
        items_by_id[item_id].position = i

    await db.commit()
    return {"status": "ok"}
