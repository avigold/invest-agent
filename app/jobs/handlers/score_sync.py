"""Score sync handler: re-score all companies with stale or missing scores.

Scoring-only — no data ingestion. Depends on fmp_sync / price_sync
having already refreshed the underlying data.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Company, CompanyRiskRegister, CompanyScore
from app.packets.company_packets import build_company_packet
from app.score.company import compute_company_scores, detect_company_risks
from app.score.versions import COMPANY_CALC_VERSION

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def score_sync_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Score all companies that have stale or missing scores."""
    force = job.params.get("force", False)
    country_filter: str | None = job.params.get("country")
    batch_size = job.params.get("batch_size", 500)

    today = datetime.now(tz=timezone.utc).date()
    as_of = today.replace(day=1)

    _log(job, f"Score Sync: as_of={as_of}, force={force}")
    start_time = time.monotonic()

    async with session_factory() as db:
        # Load primary listings only (skip duplicate cross-listings)
        query = select(Company).where(
            Company.is_primary_listing == True,  # noqa: E712
        ).order_by(Company.ticker)
        if country_filter:
            query = query.where(Company.country_iso2 == country_filter.upper())
        result = await db.execute(query)
        all_companies = list(result.scalars().all())

        if not all_companies:
            _log(job, "No companies found.")
            return

        # Find companies needing scoring
        if force:
            companies_to_score = all_companies
        else:
            # Get companies that already have a current score
            result = await db.execute(
                select(CompanyScore.company_id).where(
                    CompanyScore.as_of == as_of,
                    CompanyScore.calc_version == COMPANY_CALC_VERSION,
                )
            )
            scored_ids = {row[0] for row in result.all()}
            companies_to_score = [c for c in all_companies if c.id not in scored_ids]

        total = len(companies_to_score)
        _log(job, f"Companies to score: {total} (of {len(all_companies)} total, force={force})")

        if not companies_to_score:
            _log(job, "All companies already scored for this period.")
            return

        # Process in batches
        all_scores: list[CompanyScore] = []
        all_risks: dict[str, list[CompanyRiskRegister]] = {}
        scored_count = 0

        for batch_start in range(0, total, batch_size):
            batch = companies_to_score[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size

            _log(job, f"\n--- Batch {batch_num}/{total_batches}: {len(batch)} companies ---")

            # Score batch
            scores = await compute_company_scores(
                db=db,
                companies=batch,
                as_of=as_of,
                log_fn=lambda msg: _log(job, msg),
            )

            # Delete old scores for these companies at this as_of
            company_ids = [c.id for c in batch]
            await db.execute(
                delete(CompanyScore).where(
                    CompanyScore.company_id.in_(company_ids),
                    CompanyScore.as_of == as_of,
                    CompanyScore.calc_version == COMPANY_CALC_VERSION,
                )
            )
            for score in scores:
                db.add(score)
            await db.flush()

            # Detect risks
            for score in scores:
                company = next(c for c in batch if c.id == score.company_id)
                await db.execute(
                    delete(CompanyRiskRegister).where(
                        CompanyRiskRegister.company_id == company.id,
                        CompanyRiskRegister.detected_at == as_of,
                    )
                )
                risks = detect_company_risks(
                    None, company, score, as_of, lambda msg: _log(job, msg)
                )
                for r in risks:
                    db.add(r)
                all_risks[company.ticker] = risks
            await db.flush()

            all_scores.extend(scores)
            scored_count += len(scores)

            await db.commit()
            _log(job, f"  Batch {batch_num}: {len(scores)} scored")

        # Build decision packets for all newly scored companies
        _log(job, f"\n--- Building Decision Packets ({scored_count} companies) ---")

        # Load ALL scores for global ranking
        result = await db.execute(
            select(CompanyScore).where(
                CompanyScore.as_of == as_of,
                CompanyScore.calc_version == COMPANY_CALC_VERSION,
            )
        )
        global_scores = list(result.scalars().all())
        _log(job, f"  Ranking against {len(global_scores)} total scored companies")

        packet_count = 0
        for score in all_scores:
            company = next(c for c in companies_to_score if c.id == score.company_id)
            risks = all_risks.get(company.ticker, [])
            await build_company_packet(
                db=db,
                company=company,
                score=score,
                risks=risks,
                all_scores=global_scores,
                include_evidence=True,
            )
            packet_count += 1

        await db.commit()

    elapsed = time.monotonic() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    _log(job, f"\nScore Sync complete: {scored_count} scored, {packet_count} packets in {minutes}m {seconds}s")
