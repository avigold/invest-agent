"""Company refresh handler: ingest → score → build packets."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Company, CompanyRiskRegister, CompanyScore
from app.ingest.artefact_store import ArtefactStore
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


async def company_refresh_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Orchestrate: seed sources → load config → ingest EDGAR + market → score → packets."""
    settings = get_settings()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)

    # Parse params
    ticker_filter = job.params.get("ticker")  # None = all companies
    as_of_str = job.params.get("as_of")
    force = job.params.get("force", False)

    if as_of_str:
        as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date()
    else:
        today = datetime.now(tz=timezone.utc).date()
        as_of = today.replace(day=1)

    _log(job, f"Company refresh: as_of={as_of}, force={force}")

    async with session_factory() as db:
        # 1. Seed data sources
        _log(job, "Seeding data sources...")
        sources = await seed_data_sources(db)
        await db.commit()

        # 2. Load config and upsert companies
        _log(job, "Loading company universe config...")
        config = json.loads(_CONFIG_PATH.read_text())
        companies_config = config["companies"]
        concept_map = config["edgar_concepts"]
        yf_column_map = config.get("yfinance_column_map", {})

        companies: list[Company] = []
        for cc in companies_config:
            if ticker_filter and cc["ticker"] != ticker_filter:
                continue

            result = await db.execute(
                select(Company).where(Company.ticker == cc["ticker"])
            )
            company = result.scalar_one_or_none()
            if company is None:
                company = Company(
                    ticker=cc["ticker"],
                    cik=cc.get("cik"),  # nullable for international
                    name=cc["name"],
                    gics_code=cc.get("gics_code", ""),
                    country_iso2=cc.get("country_iso2", "US"),
                )
                db.add(company)
                await db.flush()
            else:
                company.name = cc["name"]
                company.gics_code = cc.get("gics_code", "")
                company.country_iso2 = cc.get("country_iso2", "US")
            companies.append(company)

        await db.commit()

        if not companies:
            _log(job, f"No companies matched filter ticker={ticker_filter}")
            return

        _log(job, f"Processing {len(companies)} companies...")

        # 3. Ingest for each company
        all_artefact_ids: list[str] = []
        market_start = f"{as_of.year - 2}-01-01"
        market_end = str(as_of)

        total = len(companies)
        for idx, company in enumerate(companies, 1):
            _log(job, f"\n--- Company {idx}/{total}: {company.name} ({company.ticker}) ---")

            # Route fundamentals by country
            if company.country_iso2 == "US":
                # SEC EDGAR for US companies
                edgar_ids = await ingest_edgar_for_company(
                    db=db,
                    artefact_store=artefact_store,
                    edgar_source=sources["sec_edgar"],
                    company=company,
                    concept_map=concept_map,
                    log_fn=lambda msg, j=job: _log(j, msg),
                    force=force,
                )
                all_artefact_ids.extend(str(aid) for aid in edgar_ids)
            else:
                # yfinance for international companies
                yf_ids = await ingest_yfinance_fundamentals_for_company(
                    db=db,
                    artefact_store=artefact_store,
                    yf_source=sources["yfinance"],
                    company=company,
                    column_map=yf_column_map,
                    log_fn=lambda msg, j=job: _log(j, msg),
                    force=force,
                )
                all_artefact_ids.extend(str(aid) for aid in yf_ids)

            # Market data for all companies
            market_ids = await ingest_market_data_for_company(
                db=db,
                artefact_store=artefact_store,
                yf_source=sources["yfinance"],
                company=company,
                start_date=market_start,
                end_date=market_end,
                log_fn=lambda msg, j=job: _log(j, msg),
                force=force,
            )
            all_artefact_ids.extend(str(aid) for aid in market_ids)

            await db.commit()

        # 4. Score companies (absolute scoring — no need to load all)
        _log(job, "\n--- Scoring ---")
        scores = await compute_company_scores(
            db=db,
            companies=companies,
            as_of=as_of,
            log_fn=lambda msg, j=job: _log(j, msg),
        )

        # Delete old scores for this as_of
        await db.execute(
            delete(CompanyScore).where(
                CompanyScore.as_of == as_of,
                CompanyScore.calc_version == COMPANY_CALC_VERSION,
            )
        )
        for score in scores:
            db.add(score)
        await db.flush()

        # 5. Detect risks
        _log(job, "\n--- Risk Detection ---")
        all_risks: dict[str, list[CompanyRiskRegister]] = {}
        for score in scores:
            company = next(c for c in companies if c.id == score.company_id)
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

        # 6. Build decision packets
        _log(job, "\n--- Building Decision Packets ---")
        packet_ids: list[str] = []
        for score in scores:
            company = next(c for c in companies if c.id == score.company_id)
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

        _log(job, f"\nCompany refresh complete. {len(scores)} companies scored, {len(packet_ids)} packets built.")
