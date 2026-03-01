"""yfinance financial statements ingest for international companies."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date
from functools import partial
from typing import Callable

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanySeries, CompanySeriesPoint, DataSource
from app.ingest.artefact_store import ArtefactStore

# Metrics where yfinance reports negative values that should be positive
_ABSOLUTE_VALUE_METRICS = {"capex"}


def _fetch_yfinance_financials(ticker_symbol: str) -> dict:
    """Fetch income_stmt, balance_sheet, cashflow from yfinance (sync, run in executor).

    Returns dict with keys "income_stmt", "balance_sheet", "cashflow",
    each containing a dict of {column_name: {date_str: value}}.
    """
    ticker = yf.Ticker(ticker_symbol)

    result = {}
    for attr_name in ("income_stmt", "balance_sheet", "cashflow"):
        df = getattr(ticker, attr_name, None)
        if df is None or df.empty:
            result[attr_name] = {}
            continue
        # DataFrame: rows = financial items, columns = dates
        # Convert to {item_name: {date_str: value}}
        serialized = {}
        for item_name in df.index:
            row = {}
            for col_date in df.columns:
                val = df.loc[item_name, col_date]
                if val is not None and str(val) != "nan":
                    date_key = col_date.strftime("%Y-%m-%d") if hasattr(col_date, "strftime") else str(col_date)
                    row[date_key] = float(val)
            if row:
                serialized[item_name] = row
        result[attr_name] = serialized

    return result


def _extract_series_from_financials(
    financials: dict,
    column_map: dict[str, list[str]],
) -> dict[str, list[dict]]:
    """Extract annual values for each metric using fallback column chains.

    Args:
        financials: output of _fetch_yfinance_financials
        column_map: {series_name: [primary_col, fallback_col, ...]}

    Returns {series_name: [{fiscal_year: YYYY, value: float}, ...]} sorted by year desc.
    """
    # Map series to their source DataFrame
    _SERIES_TO_DF = {
        "revenue": "income_stmt",
        "net_income": "income_stmt",
        "operating_income": "income_stmt",
        "eps_diluted": "income_stmt",
        "total_assets": "balance_sheet",
        "total_liabilities": "balance_sheet",
        "stockholders_equity": "balance_sheet",
        "cash_from_ops": "cashflow",
        "capex": "cashflow",
    }

    result: dict[str, list[dict]] = {}

    for series_name, col_names in column_map.items():
        df_key = _SERIES_TO_DF.get(series_name)
        if df_key is None:
            continue

        df_data = financials.get(df_key, {})
        if not df_data:
            continue

        # Try each column name in the fallback chain
        values_by_date = None
        for col_name in col_names:
            if col_name in df_data:
                values_by_date = df_data[col_name]
                break

        if not values_by_date:
            continue

        # Convert to list of {fiscal_year, value}
        points = []
        for date_str, value in values_by_date.items():
            try:
                year = int(date_str[:4])
            except (ValueError, IndexError):
                continue

            # Normalize: capex should be positive
            if series_name in _ABSOLUTE_VALUE_METRICS:
                value = abs(value)

            points.append({"fiscal_year": year, "value": value})

        # Sort by fiscal year descending
        points.sort(key=lambda p: p["fiscal_year"], reverse=True)
        if points:
            result[series_name] = points

    return result


async def ingest_yfinance_fundamentals_for_company(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    yf_source: DataSource,
    company: Company,
    column_map: dict[str, list[str]],
    log_fn: Callable[[str], None],
) -> list[uuid.UUID]:
    """Fetch yfinance financial statements, store artefact + series points.

    Returns list of artefact IDs created.
    """
    artefact_ids: list[uuid.UUID] = []
    symbol = company.ticker
    log_fn(f"  yfinance fundamentals: {symbol}")

    loop = asyncio.get_running_loop()
    try:
        financials = await loop.run_in_executor(
            None, partial(_fetch_yfinance_financials, symbol),
        )
    except Exception as e:
        log_fn(f"    WARN: Failed to fetch yfinance data for {symbol}: {e}")
        return []

    # Check if we got any data at all
    has_data = any(bool(v) for v in financials.values())
    if not has_data:
        log_fn(f"    WARN: No financial statements available for {symbol}")
        return []

    # Store the raw financials as an artefact
    raw_json = json.dumps(financials, default=str)
    artefact = await artefact_store.store(
        db=db,
        data_source_id=yf_source.id,
        source_url=f"yfinance://{symbol}/financials",
        fetch_params={"symbol": symbol, "type": "financials"},
        content=raw_json,
    )
    artefact_ids.append(artefact.id)

    # Extract and store each metric as a series
    series_data = _extract_series_from_financials(financials, column_map)

    for series_name, points in series_data.items():
        if not points:
            continue

        # Upsert series
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
                indicator_code=series_name,
                unit="usd",
                frequency="annual",
            )
            db.add(series)
            await db.flush()

        # Upsert points
        for pt in points:
            fy = int(pt["fiscal_year"])
            stmt = pg_insert(CompanySeriesPoint).values(
                id=uuid.uuid4(),
                series_id=series.id,
                artefact_id=artefact.id,
                date=date(fy, 12, 31),
                value=pt["value"],
            ).on_conflict_do_update(
                constraint="uq_company_series_point_date",
                set_={"value": pt["value"], "artefact_id": artefact.id},
            )
            await db.execute(stmt)

        log_fn(f"    {series_name}: {len(points)} annual values")

    return artefact_ids
