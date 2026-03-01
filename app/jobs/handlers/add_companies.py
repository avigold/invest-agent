"""Handler for add_companies_by_market_cap job command.

Uses yfinance's screener API to get US equities pre-sorted by market cap
(paginated, 250 per request), inserts the top N not already in DB,
then runs ingest + scoring for those new companies.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Company, CompanyRiskRegister, CompanyScore
from app.ingest.artefact_store import ArtefactStore
from app.ingest.company_lookup import SECTickerCache
from app.ingest.seed_sources import seed_data_sources
from app.ingest.sec_edgar import ingest_edgar_for_company
from app.ingest.company_marketdata import ingest_market_data_for_company
from app.ingest.yfinance_fundamentals import ingest_yfinance_fundamentals_for_company
from app.score.company import compute_company_scores, detect_company_risks
from app.score.versions import COMPANY_CALC_VERSION
from app.packets.company_packets import build_company_packet

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "company_universe_v2.json"


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


def _fetch_screener_page(offset: int, size: int = 250) -> dict:
    """Fetch one page of US equities sorted by market cap (sync, run in executor)."""
    import yfinance as yf

    q = yf.EquityQuery("and", [
        yf.EquityQuery("gt", ["intradaymarketcap", 0]),
        yf.EquityQuery("eq", ["region", "us"]),
    ])
    return yf.screen(
        q, sortField="intradaymarketcap", sortAsc=False,
        offset=offset, size=size,
    )


async def add_companies_by_market_cap_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Find the next N companies by market cap, add them, ingest data, and score."""
    count = job.params.get("count", 100)
    settings = get_settings()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)

    today = datetime.now(tz=timezone.utc).date()
    as_of = today.replace(day=1)

    _log(job, f"Add companies by market cap: target={count}, as_of={as_of}")

    async with session_factory() as db:
        # ── Phase 1: Find and insert new companies ────────────────────────

        # 1. Get all tickers already in DB
        result = await db.execute(select(Company.ticker))
        existing_tickers = {row[0] for row in result.all()}
        _log(job, f"Existing companies in DB: {len(existing_tickers)}")

        # 2. Load SEC ticker cache for CIK lookups
        _log(job, "Loading SEC ticker cache for CIK lookups...")
        await SECTickerCache.get_entries()

        # 3. Page through yfinance screener (pre-sorted by market cap desc)
        _log(job, "Fetching companies from Yahoo Finance screener (sorted by market cap)...")
        loop = asyncio.get_running_loop()

        to_add: list[dict] = []
        offset = 0
        page_size = 250

        while len(to_add) < count:
            page = await loop.run_in_executor(
                None, partial(_fetch_screener_page, offset, page_size),
            )
            quotes = page.get("quotes", [])
            if not quotes:
                _log(job, f"  No more results at offset {offset}")
                break

            total = page.get("total", 0)
            _log(job, f"  Page at offset {offset}: {len(quotes)} results (total available: {total})")

            for q in quotes:
                if len(to_add) >= count:
                    break
                ticker = q.get("symbol", "")
                if not ticker or ticker in existing_tickers:
                    continue
                if any(item["ticker"] == ticker for item in to_add):
                    continue

                to_add.append({
                    "ticker": ticker,
                    "name": q.get("longName") or q.get("shortName") or ticker,
                    "market_cap": q.get("marketCap", 0),
                })

            offset += page_size
            if offset >= total:
                break

        _log(job, f"\nFound {len(to_add)} new companies to add.")

        # 4. Collect existing CIKs to skip duplicate share classes
        result = await db.execute(
            select(Company.cik).where(Company.cik.isnot(None))
        )
        existing_ciks = {row[0] for row in result.all()}

        # 5. Insert into DB
        new_companies: list[Company] = []
        skipped_dup = 0
        for item in to_add:
            cik = await SECTickerCache.lookup_cik(item["ticker"])

            if cik and cik in existing_ciks:
                skipped_dup += 1
                continue

            result = await db.execute(
                select(Company).where(Company.ticker == item["ticker"])
            )
            if result.scalar_one_or_none() is not None:
                continue

            company = Company(
                ticker=item["ticker"],
                cik=cik,
                name=item["name"],
                gics_code="",
                country_iso2="US",
                config_version="user_added",
            )
            db.add(company)
            if cik:
                existing_ciks.add(cik)
            new_companies.append(company)

            cap_b = item["market_cap"] / 1e9
            _log(job, f"  + {item['ticker']:6s} {item['name'][:40]:40s} ${cap_b:>8.1f}B")

        await db.commit()

        if skipped_dup:
            _log(job, f"Skipped {skipped_dup} duplicate share classes.")
        _log(job, f"Added {len(new_companies)} companies to the database.")

        if not new_companies:
            _log(job, "No new companies to process.")
            return

        # ── Phase 2: Ingest + score the new companies ─────────────────────

        _log(job, "\n--- Ingesting data for new companies ---")
        sources = await seed_data_sources(db)
        await db.commit()

        config = json.loads(_CONFIG_PATH.read_text())
        concept_map = config["edgar_concepts"]
        yf_column_map = config.get("yfinance_column_map", {})

        all_artefact_ids: list[str] = []
        market_start = f"{as_of.year - 2}-01-01"
        market_end = str(as_of)

        total_co = len(new_companies)
        for idx, company in enumerate(new_companies, 1):
            _log(job, f"\n--- Company {idx}/{total_co}: {company.name} ({company.ticker}) ---")

            if company.country_iso2 == "US" and company.cik:
                edgar_ids = await ingest_edgar_for_company(
                    db=db,
                    artefact_store=artefact_store,
                    edgar_source=sources["sec_edgar"],
                    company=company,
                    concept_map=concept_map,
                    log_fn=lambda msg, j=job: _log(j, msg),
                )
                all_artefact_ids.extend(str(aid) for aid in edgar_ids)
            else:
                yf_ids = await ingest_yfinance_fundamentals_for_company(
                    db=db,
                    artefact_store=artefact_store,
                    yf_source=sources["yfinance"],
                    company=company,
                    column_map=yf_column_map,
                    log_fn=lambda msg, j=job: _log(j, msg),
                )
                all_artefact_ids.extend(str(aid) for aid in yf_ids)

            market_ids = await ingest_market_data_for_company(
                db=db,
                artefact_store=artefact_store,
                yf_source=sources["yfinance"],
                company=company,
                start_date=market_start,
                end_date=market_end,
                log_fn=lambda msg, j=job: _log(j, msg),
            )
            all_artefact_ids.extend(str(aid) for aid in market_ids)

            await db.commit()

        # ── Phase 3: Score ────────────────────────────────────────────────

        _log(job, "\n--- Scoring new companies ---")
        scores = await compute_company_scores(
            db=db,
            companies=new_companies,
            as_of=as_of,
            log_fn=lambda msg, j=job: _log(j, msg),
        )

        for score in scores:
            # Delete any pre-existing score for this company+date (shouldn't exist, but safe)
            await db.execute(
                delete(CompanyScore).where(
                    CompanyScore.company_id == score.company_id,
                    CompanyScore.as_of == as_of,
                    CompanyScore.calc_version == COMPANY_CALC_VERSION,
                )
            )
            db.add(score)
        await db.flush()

        # ── Phase 4: Risks + packets ──────────────────────────────────────

        _log(job, "\n--- Risk Detection ---")
        all_risks: dict[str, list[CompanyRiskRegister]] = {}
        for score in scores:
            company = next(c for c in new_companies if c.id == score.company_id)
            await db.execute(
                delete(CompanyRiskRegister).where(
                    CompanyRiskRegister.company_id == company.id,
                    CompanyRiskRegister.detected_at == as_of,
                )
            )
            risks = detect_company_risks(
                None, company, score, as_of, lambda msg, j=job: _log(j, msg)
            )
            for r in risks:
                db.add(r)
            all_risks[company.ticker] = risks
        await db.flush()

        _log(job, "\n--- Building Decision Packets ---")
        packet_ids: list[str] = []
        for score in scores:
            company = next(c for c in new_companies if c.id == score.company_id)
            risks = all_risks.get(company.ticker, [])
            packet = await build_company_packet(
                db=db,
                company=company,
                score=score,
                risks=risks,
                all_scores=scores,
                include_evidence=True,
            )
            packet_ids.append(str(packet.id))

        await db.commit()

        job.artefact_ids = all_artefact_ids
        if packet_ids:
            job.packet_id = packet_ids[0]

        _log(job, f"\nDone. {len(new_companies)} companies added, {len(scores)} scored, {len(packet_ids)} packets built.")
