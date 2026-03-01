"""Stock market data ingest for companies via yfinance."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from functools import partial
from typing import Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanySeries, CompanySeriesPoint, DataSource
from app.ingest.artefact_store import ArtefactStore
from app.ingest.marketdata import fetch_index_history


async def ingest_market_data_for_company(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    yf_source: DataSource,
    company: Company,
    start_date: str,
    end_date: str,
    log_fn: Callable[[str], None],
) -> list[uuid.UUID]:
    """Fetch daily stock prices, store artefact + daily close points.

    Returns list of artefact IDs.
    """
    symbol = company.ticker
    log_fn(f"  Market data: {symbol}")

    loop = asyncio.get_running_loop()
    try:
        rows, raw_csv = await loop.run_in_executor(
            None, partial(fetch_index_history, symbol, start_date, end_date),
        )
    except Exception as e:
        log_fn(f"    WARN: Failed to fetch {symbol}: {e}")
        return []

    if not rows:
        log_fn(f"    No data for {symbol}")
        return []

    # Store artefact
    artefact = await artefact_store.store(
        db=db,
        data_source_id=yf_source.id,
        source_url=f"yfinance://{symbol}",
        fetch_params={"symbol": symbol, "start": start_date, "end": end_date},
        content=raw_csv,
        time_window_start=datetime.strptime(start_date, "%Y-%m-%d").date(),
        time_window_end=datetime.strptime(end_date, "%Y-%m-%d").date(),
    )

    # Upsert series
    series_name = "equity_close"
    result = await db.execute(
        select(CompanySeries).where(
            CompanySeries.company_id == company.id,
            CompanySeries.series_name == series_name,
        )
    )
    series = result.scalar_one_or_none()
    if series is None:
        series = CompanySeries(
            company_id=company.id,
            series_name=series_name,
            source="yfinance",
            indicator_code=symbol,
            unit="price",
            frequency="daily",
        )
        db.add(series)
        await db.flush()

    # Upsert points
    for row in rows:
        row_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
        stmt = pg_insert(CompanySeriesPoint).values(
            id=uuid.uuid4(),
            series_id=series.id,
            artefact_id=artefact.id,
            date=row_date,
            value=row["close"],
        ).on_conflict_do_update(
            constraint="uq_company_series_point_date",
            set_={"value": row["close"], "artefact_id": artefact.id},
        )
        await db.execute(stmt)

    log_fn(f"    Stored {len(rows)} daily prices")
    return [artefact.id]
