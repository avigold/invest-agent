"""FMP fundamentals sync handler: bulk-refresh FMP data for all DB companies.

Processes ALL companies in the database (not just config-file companies),
using shared httpx client and semaphore-based concurrency control.
Freshness-aware: skips companies whose data is still fresh (30-day window).
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Company
from app.ingest.artefact_store import ArtefactStore
from app.ingest.fmp_fundamentals import ingest_fmp_fundamentals_for_company
from app.ingest.seed_sources import seed_data_sources

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def fmp_sync_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Refresh FMP fundamentals for all companies in the database."""
    settings = get_settings()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)
    concurrency = job.params.get("concurrency", 10)
    force = job.params.get("force", False)
    country_filter: str | None = job.params.get("country")

    if not settings.fmp_api_key:
        _log(job, "ERROR: FMP_API_KEY not configured")
        return

    _log(job, f"FMP Sync: concurrency={concurrency}, force={force}")

    async with session_factory() as db:
        sources = await seed_data_sources(db)
        await db.commit()

        query = select(Company).order_by(Company.ticker)
        if country_filter:
            query = query.where(Company.country_iso2 == country_filter.upper())
        result = await db.execute(query)
        companies = list(result.scalars().all())

    if not companies:
        _log(job, "No companies found in database.")
        return

    fmp_source = sources["fmp"]
    total = len(companies)
    _log(job, f"Processing {total} companies")

    sem = asyncio.Semaphore(concurrency)
    fetched = 0
    skipped = 0
    failed = 0
    start_time = time.monotonic()

    async with httpx.AsyncClient() as client:
        async def _process(idx: int, company: Company) -> None:
            nonlocal fetched, skipped, failed
            logs: list[str] = []

            async with sem:
                try:
                    async with session_factory() as db:
                        await ingest_fmp_fundamentals_for_company(
                            db=db,
                            artefact_store=artefact_store,
                            fmp_source=fmp_source,
                            company=company,
                            api_key=settings.fmp_api_key,
                            log_fn=logs.append,
                            force=force,
                            client=client,
                        )
                        await db.commit()

                    was_skipped = any("skipped" in l.lower() for l in logs)
                    if was_skipped:
                        skipped += 1
                    else:
                        fetched += 1

                    # Log every 100th company or on fetch (not skip)
                    if not was_skipped or idx % 100 == 0:
                        status = "skipped (fresh)" if was_skipped else "fetched"
                        _log(job, f"[{idx:>{len(str(total))}}/{total}] {company.ticker}: {status}")

                except Exception as e:
                    failed += 1
                    _log(job, f"[{idx:>{len(str(total))}}/{total}] {company.ticker}: FAILED ({e})")

        tasks = [_process(i, c) for i, c in enumerate(companies, 1)]
        await asyncio.gather(*tasks)

    elapsed = time.monotonic() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    _log(job, f"\nFMP Sync complete: {fetched} fetched, {skipped} skipped, {failed} failed in {minutes}m {seconds}s")
