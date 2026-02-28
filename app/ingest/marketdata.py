"""Equity index market data ingest via yfinance."""
from __future__ import annotations

import asyncio
import csv
import io
import uuid
from datetime import date, datetime
from functools import partial
from typing import Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Country, CountrySeries, CountrySeriesPoint, DataSource
from app.ingest.artefact_store import ArtefactStore


def fetch_index_history(
    symbol: str,
    start: str,
    end: str,
) -> tuple[list[dict], str]:
    """Fetch daily OHLCV data via yfinance.

    Synchronous — caller wraps in run_in_executor.
    Returns (rows, raw_csv_text).
    """
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, end=end)
    if df.empty:
        return [], ""

    rows = []
    for dt_index, row in df.iterrows():
        d = dt_index
        if hasattr(d, "date"):
            d = d.date()
        rows.append({"date": str(d), "close": float(row["Close"])})

    raw_csv = df.to_csv()
    return rows, raw_csv


async def ingest_market_data_for_country(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    yf_source: DataSource,
    country: Country,
    start_date: str,
    end_date: str,
    log_fn: Callable[[str], None],
) -> list[uuid.UUID]:
    """Fetch equity index data, store artefact + daily close points.

    Returns list of artefact IDs.
    """
    symbol = country.equity_index_symbol
    if not symbol:
        log_fn(f"  Market data: No index symbol for {country.iso2}, skipping")
        return []

    log_fn(f"  Market data: {country.iso2} / {symbol}")

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
        select(CountrySeries).where(
            CountrySeries.country_id == country.id,
            CountrySeries.series_name == series_name,
        )
    )
    series = result.scalar_one_or_none()
    if series is None:
        series = CountrySeries(
            country_id=country.id,
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
        stmt = pg_insert(CountrySeriesPoint).values(
            id=uuid.uuid4(),
            series_id=series.id,
            artefact_id=artefact.id,
            date=row_date,
            value=row["close"],
        ).on_conflict_do_update(
            constraint="uq_series_point_date",
            set_={"value": row["close"], "artefact_id": artefact.id},
        )
        await db.execute(stmt)

    log_fn(f"    Stored {len(rows)} daily prices")
    return [artefact.id]
