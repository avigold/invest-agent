"""Price sync handler: refresh stock prices for all companies and country indices.

Uses FMP for company stock prices (JSONB storage) and yfinance for country equity
index prices. Freshness-aware (4-hour window for market data).
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Company, Country, DataSource
from app.ingest.artefact_store import ArtefactStore
from app.ingest.fmp_prices import ingest_fmp_prices_for_company
from app.ingest.marketdata import ingest_market_data_for_country
from app.ingest.seed_sources import seed_data_sources

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob

_COUNTRY_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "investable_countries_v1.json"


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def price_sync_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Refresh stock prices for all companies and country equity indices."""
    settings = get_settings()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)
    concurrency = job.params.get("concurrency", 10)
    force = job.params.get("force", False)
    country_filter: str | None = job.params.get("country")

    today = datetime.now(tz=timezone.utc).date()
    fmp_api_key = settings.fmp_api_key

    _log(job, f"Price Sync: concurrency={concurrency}")

    async with session_factory() as db:
        sources = await seed_data_sources(db)
        await db.commit()
        fmp_source = sources.get("fmp")

        # --- Country indices (yfinance — these are index tickers, not company stocks) ---
        _log(job, "\n=== Country Indices ===")
        as_of = today.replace(day=1)
        market_start = f"{as_of.year - 2}-01-01"
        market_end = str(today)
        country_config = json.loads(_COUNTRY_CONFIG_PATH.read_text())
        countries_cfg = country_config["countries"]

        for cc in countries_cfg:
            result = await db.execute(
                select(Country).where(Country.iso2 == cc["iso2"])
            )
            country = result.scalar_one_or_none()
            if country is None:
                continue

            try:
                await ingest_market_data_for_country(
                    db=db, artefact_store=artefact_store,
                    yf_source=sources["yfinance"], country=country,
                    start_date=market_start, end_date=market_end,
                    log_fn=lambda msg: _log(job, msg), force=force,
                )
                await db.commit()
            except Exception as e:
                _log(job, f"  {country.iso2}: FAILED ({e})")

        # --- Company stock prices via FMP ---
        query = select(Company).order_by(Company.ticker)
        if country_filter:
            query = query.where(Company.country_iso2 == country_filter.upper())
        result = await db.execute(query)
        companies = list(result.scalars().all())

    if not companies:
        _log(job, "No companies found.")
        return

    if not fmp_api_key:
        _log(job, "FMP_API_KEY not set, skipping company prices.")
        return

    total = len(companies)
    _log(job, f"\n=== Company Prices ({total} companies, FMP → JSONB) ===")

    sem = asyncio.Semaphore(concurrency)
    fetched = 0
    skipped = 0
    no_data = 0
    failed = 0
    start_time = time.monotonic()

    async with httpx.AsyncClient() as client:
        async def _process(idx: int, company: Company) -> None:
            nonlocal fetched, skipped, no_data, failed
            logs: list[str] = []

            async with sem:
                try:
                    async with session_factory() as db:
                        artefact_ids = await ingest_fmp_prices_for_company(
                            db=db, artefact_store=artefact_store,
                            fmp_source=fmp_source, company=company,
                            api_key=fmp_api_key,
                            log_fn=logs.append, force=force,
                            client=client,
                        )
                        await db.commit()

                    was_skipped = any("skipped" in l.lower() or "fresh" in l.lower() for l in logs)
                    was_no_data = any("no price data" in l.lower() for l in logs)

                    if was_skipped:
                        skipped += 1
                    elif was_no_data:
                        no_data += 1
                    else:
                        fetched += 1

                    if idx % 100 == 0:
                        elapsed = time.monotonic() - start_time
                        rate = idx / elapsed if elapsed > 0 else 0
                        eta_min = int((total - idx) / rate / 60) if rate > 0 else 0
                        _log(job, f"[{idx}/{total}] fetched={fetched} no_data={no_data} failed={failed} ({elapsed:.0f}s, {rate:.1f}/s, ETA ~{eta_min}m)")

                except Exception as e:
                    failed += 1
                    if failed <= 10:
                        _log(job, f"[{idx}/{total}] {company.ticker}: FAILED ({e})")

        tasks = [_process(i, c) for i, c in enumerate(companies, 1)]
        await asyncio.gather(*tasks)

    elapsed = time.monotonic() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    _log(job, f"\nPrice Sync complete: {fetched} fetched, {skipped} skipped, {no_data} no_data, {failed} failed in {minutes}m {seconds}s")
