"""Country refresh handler: ingest → score → build packets."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Country, CountryRiskRegister, CountryScore, DecisionPacket
from app.ingest.artefact_store import ArtefactStore
from app.ingest.seed_sources import seed_data_sources
from app.ingest.world_bank import ingest_world_bank_for_country
from app.ingest.fred import ingest_fred_for_country
from app.ingest.marketdata import ingest_market_data_for_country
from app.ingest.imf import ingest_imf_for_country
from app.ingest.gdelt import ingest_gdelt_stability
from app.score.country import compute_country_scores, detect_country_risks
from app.packets.country_packets import build_country_packet

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "investable_countries_v1.json"


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def country_refresh_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Orchestrate: seed sources → load config → ingest → score → packets."""
    settings = get_settings()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)

    # Parse params
    iso2_filter = job.params.get("iso2")  # None = all countries
    as_of_str = job.params.get("as_of")
    start_year = job.params.get("start_year", 2015)

    if as_of_str:
        as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date()
    else:
        today = datetime.now(tz=timezone.utc).date()
        as_of = today.replace(day=1)

    _log(job, f"Country refresh: as_of={as_of}, start_year={start_year}")

    async with session_factory() as db:
        # 1. Seed data sources
        _log(job, "Seeding data sources...")
        sources = await seed_data_sources(db)
        await db.commit()

        # 2. Load config and upsert countries
        _log(job, "Loading country config...")
        config = json.loads(_CONFIG_PATH.read_text())
        countries_config = config["countries"]
        wb_indicators = config["world_bank_indicators"]
        imf_indicators = config.get("imf_indicators", {})
        fred_series = config["fred_series"]

        countries: list[Country] = []
        for cc in countries_config:
            if iso2_filter and cc["iso2"] != iso2_filter:
                continue

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
            else:
                country.name = cc["name"]
                country.equity_index_symbol = cc["equity_index_symbol"]
            countries.append(country)

        await db.commit()

        if not countries:
            _log(job, f"No countries matched filter iso2={iso2_filter}")
            return

        _log(job, f"Processing {len(countries)} countries...")

        # 3. Ingest for each country
        all_artefact_ids: list[str] = []
        end_year = as_of.year
        market_start = f"{end_year - 2}-01-01"
        market_end = str(as_of)
        fred_start = f"{end_year - 2}-01-01"
        fred_end = str(as_of)

        for country in countries:
            _log(job, f"\n--- {country.name} ({country.iso2}) ---")

            # World Bank
            _log(job, "Ingesting World Bank data...")
            wb_ids = await ingest_world_bank_for_country(
                db=db,
                artefact_store=artefact_store,
                wb_source=sources["world_bank"],
                country=country,
                indicators=wb_indicators,
                start_year=start_year,
                end_year=end_year,
                log_fn=lambda msg: _log(job, msg),
            )
            all_artefact_ids.extend(str(aid) for aid in wb_ids)

            # IMF WEO
            if imf_indicators:
                _log(job, "Ingesting IMF WEO data...")
                imf_ids = await ingest_imf_for_country(
                    db=db,
                    artefact_store=artefact_store,
                    imf_source=sources["imf"],
                    country=country,
                    indicators=imf_indicators,
                    start_year=start_year,
                    end_year=end_year,
                    log_fn=lambda msg: _log(job, msg),
                )
                all_artefact_ids.extend(str(aid) for aid in imf_ids)

            # FRED (applied to all countries as global risk proxy)
            _log(job, "Ingesting FRED data...")
            fred_ids = await ingest_fred_for_country(
                db=db,
                artefact_store=artefact_store,
                fred_source=sources["fred"],
                country=country,
                fred_series=fred_series,
                api_key=settings.fred_api_key,
                start_date=fred_start,
                end_date=fred_end,
                log_fn=lambda msg: _log(job, msg),
            )
            all_artefact_ids.extend(str(aid) for aid in fred_ids)

            # Market data
            _log(job, "Ingesting market data...")
            market_ids = await ingest_market_data_for_country(
                db=db,
                artefact_store=artefact_store,
                yf_source=sources["yfinance"],
                country=country,
                start_date=market_start,
                end_date=market_end,
                log_fn=lambda msg: _log(job, msg),
            )
            all_artefact_ids.extend(str(aid) for aid in market_ids)

            # GDELT stability
            _log(job, "Computing stability index...")
            gdelt_ids = await ingest_gdelt_stability(
                db=db,
                artefact_store=artefact_store,
                gdelt_source=sources["gdelt"],
                country=country,
                as_of=as_of,
                log_fn=lambda msg: _log(job, msg),
            )
            all_artefact_ids.extend(str(aid) for aid in gdelt_ids)

            await db.commit()

        # 4. Score all countries (need all for percentile ranking)
        # If we're only refreshing one country, we still need all for ranking
        if iso2_filter:
            result = await db.execute(select(Country))
            all_countries = list(result.scalars().all())
        else:
            all_countries = countries

        _log(job, "\n--- Scoring ---")
        scores = await compute_country_scores(
            db=db,
            countries=all_countries,
            as_of=as_of,
            log_fn=lambda msg: _log(job, msg),
        )

        # Delete old scores for this as_of before inserting new ones
        from app.score.versions import COUNTRY_CALC_VERSION
        await db.execute(
            delete(CountryScore).where(
                CountryScore.as_of == as_of,
                CountryScore.calc_version == COUNTRY_CALC_VERSION,
            )
        )
        for score in scores:
            db.add(score)
        await db.flush()

        # 5. Detect risks
        _log(job, "\n--- Risk Detection ---")
        all_risks: dict[str, list[CountryRiskRegister]] = {}
        for score in scores:
            country = next(c for c in all_countries if c.id == score.country_id)
            # Clear old risks for this country + date
            await db.execute(
                delete(CountryRiskRegister).where(
                    CountryRiskRegister.country_id == country.id,
                    CountryRiskRegister.detected_at == as_of,
                )
            )
            risks = await detect_country_risks(db, country, score, as_of, lambda msg: _log(job, msg))
            for r in risks:
                db.add(r)
            all_risks[country.iso2] = risks

        await db.flush()

        # 6. Build decision packets
        _log(job, "\n--- Building Decision Packets ---")
        packet_ids: list[str] = []
        for score in scores:
            country = next(c for c in all_countries if c.id == score.country_id)
            risks = all_risks.get(country.iso2, [])
            packet = await build_country_packet(
                db=db,
                country=country,
                score=score,
                risks=risks,
                all_scores=scores,
                include_evidence=True,
            )
            packet_ids.append(str(packet.id))
            _log(job, f"  Built packet for {country.iso2} (rank {packet.content.get('rank', '?')}/{len(scores)})")

        await db.commit()

        # Store references on job
        job.artefact_ids = all_artefact_ids
        if packet_ids:
            job.packet_id = packet_ids[0]  # Primary packet (first country or single country)

        _log(job, f"\nCountry refresh complete. {len(scores)} countries scored, {len(packet_ids)} packets built.")
