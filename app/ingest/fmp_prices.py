"""FMP historical price ingest for company stock prices.

Uses FMP's light EOD endpoint for fast, paginated daily price history.
Stores full history as JSONB in company_price_history for fast bulk writes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanyPriceHistory, DataSource
from app.ingest.artefact_store import ArtefactStore
from app.ingest.freshness import FRESHNESS_HOURS
from app.ingest.fmp import fetch_historical_prices


async def ingest_fmp_prices_for_company(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    fmp_source: DataSource,
    company: Company,
    api_key: str,
    log_fn: Callable[[str], None],
    force: bool = False,
    client: httpx.AsyncClient | None = None,
    from_date: str = "1970-01-01",
    to_date: str | None = None,
) -> list[uuid.UUID]:
    """Fetch FMP daily prices, store artefact + JSONB price history.

    Returns list of artefact IDs created.
    """
    symbol = company.ticker
    log_fn(f"  FMP prices: {symbol}")

    # Freshness check — reuse yfinance_market window (4h)
    if not force:
        existing = await artefact_store.find_fresh(
            db, fmp_source.id,
            {"symbol": symbol, "type": "historical_prices"},
            FRESHNESS_HOURS["yfinance_market"],
        )
        if existing is not None:
            log_fn("    Skipped (fresh)")
            return [existing.id]

    # Fetch prices
    async def _fetch(c: httpx.AsyncClient) -> tuple[list[dict], str]:
        return await fetch_historical_prices(c, symbol, api_key, from_date, to_date)

    try:
        if client is not None:
            rows, raw = await _fetch(client)
        else:
            async with httpx.AsyncClient() as _c:
                rows, raw = await _fetch(_c)
    except httpx.HTTPError as e:
        log_fn(f"    WARN: FMP prices failed for {symbol}: {e}")
        return []

    if not rows:
        log_fn(f"    No price data for {symbol}")
        return []

    # Store artefact
    artefact = await artefact_store.store(
        db=db,
        data_source_id=fmp_source.id,
        source_url=f"https://financialmodelingprep.com/stable/historical-price-eod/light?symbol={symbol}",
        fetch_params={"symbol": symbol, "type": "historical_prices"},
        content=raw,
    )

    # Upsert single JSONB row per company
    from datetime import date as date_type
    first_date = datetime.strptime(rows[0]["date"], "%Y-%m-%d").date() if rows else None
    last_date = datetime.strptime(rows[-1]["date"], "%Y-%m-%d").date() if rows else None

    stmt = pg_insert(CompanyPriceHistory).values(
        id=uuid.uuid4(),
        company_id=company.id,
        prices=rows,  # [{date, price, volume}, ...] sorted oldest-first
        first_date=first_date,
        last_date=last_date,
        num_points=len(rows),
        updated_at=datetime.now(tz=timezone.utc),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["company_id"],
        set_={
            "prices": stmt.excluded.prices,
            "first_date": stmt.excluded.first_date,
            "last_date": stmt.excluded.last_date,
            "num_points": stmt.excluded.num_points,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await db.execute(stmt)

    log_fn(f"    {len(rows)} daily prices")
    return [artefact.id]
