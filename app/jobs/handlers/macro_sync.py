"""Macro data sync handler: country-level data refresh.

Supports two scopes:
  - "daily": FRED series + country equity index prices (fast, run daily)
  - "monthly": All sources — World Bank, IMF, FRED, GDELT, market (run monthly)

Replaces the country portion of the old data_sync handler with
scope-aware scheduling.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Country
from app.ingest.artefact_store import ArtefactStore
from app.ingest.fred import ingest_fred_for_country
from app.ingest.gdelt import ingest_gdelt_stability
from app.ingest.imf import ingest_imf_for_country
from app.ingest.marketdata import ingest_market_data_for_country
from app.ingest.seed_sources import seed_data_sources
from app.ingest.world_bank import ingest_world_bank_for_country

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob

_COUNTRY_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "investable_countries_v1.json"


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def macro_sync_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Refresh country-level macro data.

    Params:
        scope: "daily" (FRED + market only) or "monthly" (all sources).
               Default: "monthly".
        force: Override freshness checks. Default: False.
    """
    settings = get_settings()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)
    scope = job.params.get("scope", "monthly")
    force = job.params.get("force", False)

    today = datetime.now(tz=timezone.utc).date()
    as_of = today.replace(day=1)
    end_year = as_of.year
    start_year = 2015

    market_start = f"{end_year - 2}-01-01"
    market_end = str(as_of)
    fred_start = f"{end_year - 2}-01-01"
    fred_end = str(as_of)

    _log(job, f"Macro Sync: scope={scope}, as_of={as_of}, force={force}")

    async with session_factory() as db:
        sources = await seed_data_sources(db)
        await db.commit()

        # Load country config
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

        _log(job, f"Processing {len(countries)} countries (scope={scope})")

        for country in countries:
            _log(job, f"\n--- {country.name} ({country.iso2}) ---")

            # World Bank — monthly scope only
            if scope == "monthly":
                await ingest_world_bank_for_country(
                    db=db, artefact_store=artefact_store,
                    wb_source=sources["world_bank"], country=country,
                    indicators=wb_indicators, start_year=start_year,
                    end_year=end_year, log_fn=lambda msg: _log(job, msg),
                    force=force,
                )

            # IMF WEO — monthly scope only
            if scope == "monthly" and imf_indicators:
                await ingest_imf_for_country(
                    db=db, artefact_store=artefact_store,
                    imf_source=sources["imf"], country=country,
                    indicators=imf_indicators, start_year=start_year,
                    end_year=end_year, log_fn=lambda msg: _log(job, msg),
                    force=force,
                )

            # FRED — both scopes (24h freshness handles daily vs monthly)
            await ingest_fred_for_country(
                db=db, artefact_store=artefact_store,
                fred_source=sources["fred"], country=country,
                fred_series=fred_series, api_key=settings.fred_api_key,
                start_date=fred_start, end_date=fred_end,
                log_fn=lambda msg: _log(job, msg), force=force,
            )

            # Market data — both scopes
            await ingest_market_data_for_country(
                db=db, artefact_store=artefact_store,
                yf_source=sources["yfinance"], country=country,
                start_date=market_start, end_date=market_end,
                log_fn=lambda msg: _log(job, msg), force=force,
            )

            # GDELT — monthly scope only
            if scope == "monthly":
                await ingest_gdelt_stability(
                    db=db, artefact_store=artefact_store,
                    gdelt_source=sources["gdelt"], country=country,
                    as_of=as_of, log_fn=lambda msg: _log(job, msg),
                    force=force,
                )

            await db.commit()

        _log(job, f"\nMacro Sync ({scope}) complete.")
