"""Data sync handler: ingest-only refresh for all countries and companies.

Fetches all external data respecting freshness windows — no scoring.
Designed for scheduler automation and manual data updates.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Company, Country
from app.ingest.artefact_store import ArtefactStore
from app.ingest.seed_sources import seed_data_sources
from app.ingest.world_bank import ingest_world_bank_for_country
from app.ingest.fred import ingest_fred_for_country
from app.ingest.marketdata import ingest_market_data_for_country
from app.ingest.imf import ingest_imf_for_country
from app.ingest.gdelt import ingest_gdelt_stability
from app.ingest.sec_edgar import ingest_edgar_for_company
from app.ingest.company_marketdata import ingest_market_data_for_company
from app.ingest.yfinance_fundamentals import ingest_yfinance_fundamentals_for_company

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob

_COUNTRY_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "investable_countries_v1.json"
_COMPANY_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "company_universe_v2.json"


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def data_sync_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ingest all external data for all countries and companies.

    Respects freshness windows — only fetches data that is stale.
    Does NOT run scoring or build packets (use country_refresh / company_refresh for that).
    """
    settings = get_settings()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)
    force = job.params.get("force", False)

    today = datetime.now(tz=timezone.utc).date()
    as_of = today.replace(day=1)

    _log(job, f"Data sync: as_of={as_of}, force={force}")

    async with session_factory() as db:
        # Seed data sources
        sources = await seed_data_sources(db)
        await db.commit()

        # --- Country data ---
        country_config = json.loads(_COUNTRY_CONFIG_PATH.read_text())
        countries_cfg = country_config["countries"]
        wb_indicators = country_config["world_bank_indicators"]
        imf_indicators = country_config.get("imf_indicators", {})
        fred_series = country_config["fred_series"]

        # Upsert countries
        countries: list[Country] = []
        for cc in countries_cfg:
            result = await db.execute(
                select(Country).where(Country.iso2 == cc["iso2"])
            )
            country = result.scalar_one_or_none()
            if country is None:
                country = Country(
                    iso2=cc["iso2"],
                    iso3=cc["iso3"],
                    name=cc["name"],
                    equity_index_symbol=cc["equity_index_symbol"],
                )
                db.add(country)
                await db.flush()
            countries.append(country)
        await db.commit()

        end_year = as_of.year
        start_year = 2015
        market_start = f"{end_year - 2}-01-01"
        market_end = str(as_of)
        fred_start = f"{end_year - 2}-01-01"
        fred_end = str(as_of)

        fetched = 0
        skipped = 0

        _log(job, f"\n=== Country data ({len(countries)} countries) ===")

        for country in countries:
            _log(job, f"\n--- {country.name} ({country.iso2}) ---")

            # World Bank
            wb_ids = await ingest_world_bank_for_country(
                db=db, artefact_store=artefact_store,
                wb_source=sources["world_bank"], country=country,
                indicators=wb_indicators, start_year=start_year,
                end_year=end_year, log_fn=lambda msg: _log(job, msg),
                force=force,
            )

            # IMF WEO
            if imf_indicators:
                await ingest_imf_for_country(
                    db=db, artefact_store=artefact_store,
                    imf_source=sources["imf"], country=country,
                    indicators=imf_indicators, start_year=start_year,
                    end_year=end_year, log_fn=lambda msg: _log(job, msg),
                    force=force,
                )

            # FRED
            await ingest_fred_for_country(
                db=db, artefact_store=artefact_store,
                fred_source=sources["fred"], country=country,
                fred_series=fred_series, api_key=settings.fred_api_key,
                start_date=fred_start, end_date=fred_end,
                log_fn=lambda msg: _log(job, msg), force=force,
            )

            # Market data
            await ingest_market_data_for_country(
                db=db, artefact_store=artefact_store,
                yf_source=sources["yfinance"], country=country,
                start_date=market_start, end_date=market_end,
                log_fn=lambda msg: _log(job, msg), force=force,
            )

            # GDELT
            await ingest_gdelt_stability(
                db=db, artefact_store=artefact_store,
                gdelt_source=sources["gdelt"], country=country,
                as_of=as_of, log_fn=lambda msg: _log(job, msg),
                force=force,
            )

            await db.commit()

        # --- Company data ---
        company_config = json.loads(_COMPANY_CONFIG_PATH.read_text())
        companies_cfg = company_config["companies"]
        concept_map = company_config["edgar_concepts"]
        yf_column_map = company_config.get("yfinance_column_map", {})

        # Upsert companies
        companies: list[Company] = []
        for cc in companies_cfg:
            result = await db.execute(
                select(Company).where(Company.ticker == cc["ticker"])
            )
            company = result.scalar_one_or_none()
            if company is None:
                company = Company(
                    ticker=cc["ticker"],
                    cik=cc.get("cik"),
                    name=cc["name"],
                    gics_code=cc.get("gics_code", ""),
                    country_iso2=cc.get("country_iso2", "US"),
                )
                db.add(company)
                await db.flush()
            companies.append(company)
        await db.commit()

        _log(job, f"\n=== Company data ({len(companies)} companies) ===")

        for idx, company in enumerate(companies, 1):
            _log(job, f"\n--- Company {idx}/{len(companies)}: {company.name} ({company.ticker}) ---")

            # Route fundamentals by country
            if company.country_iso2 == "US":
                await ingest_edgar_for_company(
                    db=db, artefact_store=artefact_store,
                    edgar_source=sources["sec_edgar"], company=company,
                    concept_map=concept_map,
                    log_fn=lambda msg, j=job: _log(j, msg), force=force,
                )
            else:
                await ingest_yfinance_fundamentals_for_company(
                    db=db, artefact_store=artefact_store,
                    yf_source=sources["yfinance"], company=company,
                    column_map=yf_column_map,
                    log_fn=lambda msg, j=job: _log(j, msg), force=force,
                )

            # Market data
            await ingest_market_data_for_company(
                db=db, artefact_store=artefact_store,
                yf_source=sources["yfinance"], company=company,
                start_date=market_start, end_date=market_end,
                log_fn=lambda msg, j=job: _log(j, msg), force=force,
            )

            await db.commit()

        _log(job, f"\nData sync complete.")
