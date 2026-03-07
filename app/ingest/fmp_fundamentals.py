"""FMP financial statements ingest for company scoring pipeline."""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanySeries, CompanySeriesPoint, DataSource
from app.ingest.artefact_store import ArtefactStore
from app.ingest.freshness import FRESHNESS_HOURS
from app.ingest.fmp import fetch_balance_sheet, fetch_cash_flow, fetch_income_statement

# FMP field mapping: our_series_name -> (statement_type, fmp_field_name)
_FMP_FIELD_MAP: dict[str, tuple[str, str]] = {
    "revenue": ("income", "revenue"),
    "net_income": ("income", "netIncome"),
    "operating_income": ("income", "operatingIncome"),
    "eps_diluted": ("income", "epsDiluted"),
    "total_assets": ("balance", "totalAssets"),
    "total_liabilities": ("balance", "totalLiabilities"),
    "stockholders_equity": ("balance", "totalStockholdersEquity"),
    "cash_from_ops": ("cashflow", "operatingCashFlow"),
    "capex": ("cashflow", "capitalExpenditure"),
}


def _fiscal_year(row: dict) -> int | None:
    """Extract fiscal year from an FMP statement row.

    Prefers ``fiscalYear`` field, falls back to ``calendarYear``,
    then first 4 characters of ``date``.
    """
    for key in ("fiscalYear", "calendarYear"):
        val = row.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                continue
    d = row.get("date", "")
    if len(d) >= 4:
        try:
            return int(d[:4])
        except ValueError:
            pass
    return None


def _extract_series_from_fmp(
    income_data: list[dict],
    balance_data: list[dict],
    cashflow_data: list[dict],
) -> dict[str, list[dict]]:
    """Extract annual values for each metric from FMP statement arrays.

    Returns ``{series_name: [{fiscal_year: YYYY, value: float}, ...]}``
    sorted by fiscal year descending.
    """
    # Index by fiscal year for lookup
    statements = {
        "income": {_fiscal_year(row): row for row in income_data if _fiscal_year(row)},
        "balance": {_fiscal_year(row): row for row in balance_data if _fiscal_year(row)},
        "cashflow": {_fiscal_year(row): row for row in cashflow_data if _fiscal_year(row)},
    }

    result: dict[str, list[dict]] = {}

    for series_name, (stmt_type, fmp_field) in _FMP_FIELD_MAP.items():
        stmt_by_year = statements.get(stmt_type, {})
        points = []
        for year, row in stmt_by_year.items():
            value = row.get(fmp_field)
            if value is not None:
                try:
                    points.append({"fiscal_year": year, "value": float(value)})
                except (ValueError, TypeError):
                    continue

        points.sort(key=lambda p: p["fiscal_year"], reverse=True)
        if points:
            result[series_name] = points

    return result


async def ingest_fmp_fundamentals_for_company(
    db: AsyncSession,
    artefact_store: ArtefactStore,
    fmp_source: DataSource,
    company: Company,
    api_key: str,
    log_fn: Callable[[str], None],
    force: bool = False,
    client: httpx.AsyncClient | None = None,
) -> list[uuid.UUID]:
    """Fetch FMP financial statements, store artefacts + series points.

    Returns list of artefact IDs created.

    If *client* is provided it will be used directly (for bulk operations
    that benefit from connection pooling).  Otherwise a fresh client is
    created per call.
    """
    artefact_ids: list[uuid.UUID] = []
    symbol = company.ticker
    log_fn(f"  FMP fundamentals: {symbol}")

    # Freshness check
    if not force:
        existing = await artefact_store.find_fresh(
            db,
            fmp_source.id,
            {"symbol": symbol, "type": "income_statement"},
            FRESHNESS_HOURS["fmp_fundamentals"],
        )
        if existing is not None:
            log_fn("    Skipped (fresh)")
            return [existing.id]

    # Fetch all three statements
    async def _fetch(c: httpx.AsyncClient) -> tuple:
        income_data, income_raw = await fetch_income_statement(c, symbol, api_key)
        balance_data, balance_raw = await fetch_balance_sheet(c, symbol, api_key)
        cashflow_data, cashflow_raw = await fetch_cash_flow(c, symbol, api_key)
        return income_data, income_raw, balance_data, balance_raw, cashflow_data, cashflow_raw

    try:
        if client is not None:
            income_data, income_raw, balance_data, balance_raw, cashflow_data, cashflow_raw = (
                await _fetch(client)
            )
        else:
            async with httpx.AsyncClient() as _c:
                income_data, income_raw, balance_data, balance_raw, cashflow_data, cashflow_raw = (
                    await _fetch(_c)
                )
    except httpx.HTTPError as e:
        log_fn(f"    WARN: FMP failed for {symbol}: {e}")
        return []

    # Check if we got any data
    if not income_data and not balance_data and not cashflow_data:
        log_fn(f"    WARN: No FMP financial data for {symbol}")
        return []

    # Store each statement as a separate artefact
    stmt_specs = [
        ("income-statement", income_raw, "income_statement"),
        ("balance-sheet-statement", balance_raw, "balance_sheet"),
        ("cash-flow-statement", cashflow_raw, "cash_flow"),
    ]
    for endpoint, raw_text, params_type in stmt_specs:
        artefact = await artefact_store.store(
            db=db,
            data_source_id=fmp_source.id,
            source_url=f"https://financialmodelingprep.com/stable/{endpoint}?symbol={symbol}",
            fetch_params={"symbol": symbol, "type": params_type},
            content=raw_text,
        )
        artefact_ids.append(artefact.id)

    # Extract and store each metric as a series
    series_data = _extract_series_from_fmp(income_data, balance_data, cashflow_data)
    primary_artefact_id = artefact_ids[0]

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
                source="fmp",
                indicator_code=series_name,
                unit="usd",
                frequency="annual",
            )
            db.add(series)
            await db.flush()
        elif series.source != "fmp":
            series.source = "fmp"

        # Upsert points
        for pt in points:
            fy = int(pt["fiscal_year"])
            stmt = pg_insert(CompanySeriesPoint).values(
                id=uuid.uuid4(),
                series_id=series.id,
                artefact_id=primary_artefact_id,
                date=date(fy, 12, 31),
                value=pt["value"],
            ).on_conflict_do_update(
                constraint="uq_company_series_point_date",
                set_={"value": pt["value"], "artefact_id": primary_artefact_id},
            )
            await db.execute(stmt)

        log_fn(f"    {series_name}: {len(points)} annual values")

    return artefact_ids
