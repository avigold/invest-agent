"""Export comprehensive ML training dataset as Parquet.

Reads raw FMP artefact JSON files from disk, loads price history from
CompanyPriceHistory JSONB, computes ~200 features per company per fiscal year,
and writes a training-ready Parquet file.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select, desc, func, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Artefact,
    Company,
    CompanyPriceHistory,
    CompanyScore,
    Country,
    CountryScore,
    DataSource,
    IndustryScore,
)
from app.export.features import extract_all_features


BATCH_SIZE = 500


async def _load_fmp_source_id(db: AsyncSession) -> str | None:
    """Get the FMP data source UUID."""
    result = await db.execute(
        select(DataSource.id).where(DataSource.name == "fmp")
    )
    row = result.scalar_one_or_none()
    return str(row) if row else None


async def _load_artefacts_for_companies(
    db: AsyncSession,
    fmp_source_id: str,
    tickers: list[str],
) -> dict[str, dict[str, str]]:
    """Load FMP artefact storage URIs for a batch of companies.

    Returns {ticker: {stmt_type: storage_uri}}.
    Only loads the most recent artefact per (symbol, type).
    """
    if not tickers:
        return {}

    # Query artefacts where fetch_params has matching symbol and type
    # Use a window function to get the most recent per (symbol, type)
    rn = func.row_number().over(
        partition_by=[
            Artefact.fetch_params["symbol"].astext,
            Artefact.fetch_params["type"].astext,
        ],
        order_by=Artefact.fetched_at.desc(),
    ).label("rn")

    subq = (
        select(
            Artefact.fetch_params["symbol"].astext.label("symbol"),
            Artefact.fetch_params["type"].astext.label("stmt_type"),
            Artefact.storage_uri,
            rn,
        )
        .where(
            Artefact.data_source_id == fmp_source_id,
            Artefact.fetch_params["symbol"].astext.in_(tickers),
            Artefact.fetch_params["type"].astext.in_([
                "income_statement", "balance_sheet", "cash_flow",
            ]),
        )
        .subquery()
    )

    query = select(subq).where(subq.c.rn == 1)
    rows = await db.execute(query)

    result: dict[str, dict[str, str]] = {}
    for row in rows.all():
        symbol = row.symbol
        result.setdefault(symbol, {})[row.stmt_type] = row.storage_uri

    return result


def _load_artefact_json(storage_uri: str) -> list[dict]:
    """Load and parse a JSON artefact file from disk."""
    path = Path(storage_uri)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


async def _load_prices_batch(
    db: AsyncSession,
    company_ids: list[str],
) -> dict[str, list[dict]]:
    """Load price history JSONB for a batch of companies.

    Returns {company_id_str: [{date, price, volume}, ...]}.
    """
    if not company_ids:
        return {}

    rows = await db.execute(
        select(
            CompanyPriceHistory.company_id,
            CompanyPriceHistory.prices,
        ).where(
            CompanyPriceHistory.company_id.in_(company_ids)
        )
    )

    result: dict[str, list[dict]] = {}
    for row in rows.all():
        prices = row[1] or []
        # Normalize field names
        normalized = []
        for p in prices:
            price_val = p.get("price") or p.get("close")
            if price_val is not None:
                normalized.append({
                    "date": p["date"],
                    "price": float(price_val),
                    "volume": p.get("volume", 0),
                })
        result[str(row[0])] = normalized

    return result


async def _load_context_data(
    db: AsyncSession,
) -> dict[str, dict[str, float]]:
    """Load latest country scores as context features.

    Returns {country_iso2: {country_score: X, ...}}.
    """
    # Get latest country scores
    rn = func.row_number().over(
        partition_by=CountryScore.country_id,
        order_by=CountryScore.as_of.desc(),
    ).label("rn")

    subq = (
        select(
            CountryScore.country_id,
            CountryScore.overall_score.label("country_score"),
            rn,
        )
        .subquery()
    )

    query = (
        select(Country.iso2, subq.c.country_score)
        .join(subq, Country.id == subq.c.country_id)
        .where(subq.c.rn == 1)
    )
    rows = await db.execute(query)

    result: dict[str, dict[str, float]] = {}
    for row in rows.all():
        result[row[0]] = {"country_score": float(row[1])}

    return result


async def _load_company_scores(
    db: AsyncSession,
    company_ids: list[str],
) -> dict[str, dict[str, float]]:
    """Load latest company scores for a batch.

    Returns {company_id_str: {company_overall_score, fundamental_score, market_score}}.
    """
    if not company_ids:
        return {}

    rn = func.row_number().over(
        partition_by=CompanyScore.company_id,
        order_by=CompanyScore.as_of.desc(),
    ).label("rn")

    subq = (
        select(
            CompanyScore.company_id,
            CompanyScore.overall_score,
            CompanyScore.fundamental_score,
            CompanyScore.market_score,
            rn,
        )
        .subquery()
    )

    query = (
        select(subq)
        .where(subq.c.rn == 1, subq.c.company_id.in_(company_ids))
    )
    rows = await db.execute(query)

    result: dict[str, dict[str, float]] = {}
    for row in rows.all():
        result[str(row[0])] = {
            "company_overall_score": float(row[1]),
            "company_fundamental_score": float(row[2]),
            "company_market_score": float(row[3]),
        }

    return result


async def export_training_dataset(
    session_factory: async_sessionmaker,
    output_dir: str,
    include_prices: bool = False,
    min_years: int = 2,
    countries: list[str] | None = None,
    log_fn: Callable[[str], None] = print,
) -> None:
    """Export comprehensive training dataset as Parquet.

    Processes companies in batches of 500, reading FMP artefact JSON files
    from disk and price data from CompanyPriceHistory JSONB.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    start_time = time.monotonic()

    # Load companies
    async with session_factory() as db:
        query = select(Company).order_by(Company.ticker)
        if countries:
            query = query.where(Company.country_iso2.in_([c.upper() for c in countries]))
        result = await db.execute(query)
        companies = list(result.scalars().all())

    total = len(companies)
    if total == 0:
        log_fn("No companies found.")
        return

    log_fn(f"Exporting training data for {total} companies, batch_size={BATCH_SIZE}")

    # Load FMP source ID and context data
    async with session_factory() as db:
        fmp_source_id = await _load_fmp_source_id(db)
        context_data = await _load_context_data(db)

    if not fmp_source_id:
        log_fn("ERROR: FMP data source not found in database.")
        return

    # Process in batches
    all_rows: list[dict] = []
    price_rows: list[dict] = []
    processed = 0
    companies_with_data = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch = companies[batch_start:batch_start + BATCH_SIZE]
        batch_t0 = time.monotonic()

        tickers = [c.ticker for c in batch]
        company_ids = [str(c.id) for c in batch]
        ticker_to_company = {c.ticker: c for c in batch}

        async with session_factory() as db:
            # Load artefacts, prices, and scores in parallel-ish
            artefacts = await _load_artefacts_for_companies(db, fmp_source_id, tickers)
            prices_map = await _load_prices_batch(db, company_ids)
            scores_map = await _load_company_scores(db, company_ids)

        # Map company_id -> ticker for price lookup
        id_to_ticker = {str(c.id): c.ticker for c in batch}

        for company in batch:
            ticker = company.ticker
            art = artefacts.get(ticker, {})

            # Load statement JSON from disk
            income_rows = _load_artefact_json(art.get("income_statement", ""))
            balance_rows = _load_artefact_json(art.get("balance_sheet", ""))
            cashflow_rows = _load_artefact_json(art.get("cash_flow", ""))

            # Skip if no financial data at all
            if not income_rows and not balance_rows and not cashflow_rows:
                continue

            prices = prices_map.get(str(company.id), [])

            # Build context
            ctx = {}
            country_ctx = context_data.get(company.country_iso2, {})
            ctx.update(country_ctx)
            score_ctx = scores_map.get(str(company.id), {})
            ctx.update(score_ctx)

            # Extract all features
            rows = extract_all_features(
                income_rows=income_rows,
                balance_rows=balance_rows,
                cashflow_rows=cashflow_rows,
                prices=prices,
                index_prices=None,  # Could load per-country index, but adds complexity
                context=ctx,
            )

            # Filter by min_years
            if len(rows) < min_years:
                continue

            companies_with_data += 1

            # Add identifiers
            for row in rows:
                row["ticker"] = ticker
                row["company_name"] = company.name
                row["country_iso2"] = company.country_iso2
                row["gics_code"] = company.gics_code
                all_rows.append(row)

            # Collect price rows if requested
            if include_prices and prices:
                for p in prices:
                    price_rows.append({
                        "ticker": ticker,
                        "date": p["date"],
                        "price": p["price"],
                        "volume": p.get("volume", 0),
                        "country_iso2": company.country_iso2,
                        "gics_code": company.gics_code,
                    })

        processed += len(batch)
        batch_dt = time.monotonic() - batch_t0
        elapsed = time.monotonic() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        eta = int((total - processed) / rate) if rate > 0 else 0
        log_fn(
            f"[{processed}/{total}] batch in {batch_dt:.1f}s "
            f"({rate:.0f}/s, ETA ~{eta // 60}m{eta % 60:02d}s) "
            f"rows={len(all_rows)}"
        )

    # Write features Parquet
    if all_rows:
        features_path = output_path / "training_features.parquet"
        table = pa.Table.from_pylist(all_rows)
        pq.write_table(table, str(features_path), compression="snappy")
        log_fn(
            f"Wrote {features_path}: {len(all_rows)} rows, "
            f"{table.num_columns} columns, "
            f"{features_path.stat().st_size / 1_000_000:.1f} MB"
        )
    else:
        log_fn("No data to export.")

    # Write price series Parquet (optionally partitioned by year)
    if include_prices and price_rows:
        prices_path = output_path / "price_series.parquet"
        table = pa.Table.from_pylist(price_rows)
        pq.write_table(table, str(prices_path), compression="snappy")
        log_fn(
            f"Wrote {prices_path}: {len(price_rows)} rows, "
            f"{prices_path.stat().st_size / 1_000_000:.1f} MB"
        )

    elapsed_total = time.monotonic() - start_time
    log_fn(
        f"DONE: {companies_with_data} companies with data, "
        f"{len(all_rows)} feature rows in {elapsed_total:.0f}s"
    )
