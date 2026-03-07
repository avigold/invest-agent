"""CLI for Invest Agent."""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

import typer

app_cli = typer.Typer(name="investagent", help="Invest Agent CLI")


@app_cli.command()
def run(task: str):
    """Run a named task. Currently supported: 'daily'."""
    if task == "daily":
        typer.echo("Daily scheduler: no tasks configured yet (M1 stub).")
    else:
        typer.echo(f"Unknown task: {task}")
        raise typer.Exit(1)


@app_cli.command()
def migrate():
    """Run Alembic migrations (upgrade head)."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
    )


@app_cli.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
):
    """Start the API server."""
    import uvicorn
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


@app_cli.command()
def add_companies(
    count: int = typer.Option(1000, help="Max companies to add"),
    min_market_cap: int = typer.Option(2_000_000_000, help="Minimum market cap in USD"),
    country: Optional[str] = typer.Option(None, help="Filter by country ISO2 code"),
    preload: bool = typer.Option(True, help="Also preload FMP fundamentals for new companies"),
    concurrency: int = typer.Option(3, help="Concurrency for FMP preload"),
):
    """Discover and add companies by market cap using FMP screener.

    Finds top companies globally (or filtered by country) above the given
    market cap threshold, adds new ones to the database, and optionally
    preloads their FMP fundamental data.
    """
    import asyncio
    asyncio.run(_add_companies_async(count, min_market_cap, country, preload, concurrency))


@app_cli.command()
def preload_fmp(
    concurrency: int = typer.Option(3, help="Max parallel companies to fetch"),
    force: bool = typer.Option(False, help="Re-fetch even if data is fresh"),
    country: Optional[str] = typer.Option(None, help="Filter by country ISO2 code (e.g., US, GB)"),
):
    """Pre-load FMP fundamental data for all companies in the database.

    Respects freshness windows (30 days) — already-cached companies are
    skipped unless --force is used.  Rate-limited via --concurrency to stay
    well within FMP's 3,000 req/min limit.

    Can be run from cron, e.g.:
        0 5 * * * cd /path/to/invest-agent && .venv/bin/python -m app.cli preload-fmp
    """
    import asyncio
    asyncio.run(_preload_fmp_async(concurrency, force, country))


async def _preload_fmp_async(
    concurrency: int,
    force: bool,
    country_filter: str | None,
) -> None:
    """Async implementation of preload_fmp."""
    import time

    import httpx
    from sqlalchemy import select

    from app.config import get_settings
    from app.db.models import Company
    from app.db.session import _get_session_factory, dispose_engine
    from app.ingest.artefact_store import ArtefactStore
    from app.ingest.fmp_fundamentals import ingest_fmp_fundamentals_for_company
    from app.ingest.seed_sources import seed_data_sources

    settings = get_settings()
    if not settings.fmp_api_key:
        typer.echo("ERROR: FMP_API_KEY not configured in .env")
        raise typer.Exit(1)

    session_factory = _get_session_factory()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)

    # Load companies and seed sources
    async with session_factory() as db:
        sources = await seed_data_sources(db)
        await db.commit()

        query = select(Company).order_by(Company.ticker)
        if country_filter:
            query = query.where(Company.country_iso2 == country_filter.upper())
        result = await db.execute(query)
        companies = list(result.scalars().all())

    if not companies:
        typer.echo("No companies found in database.")
        raise typer.Exit(0)

    fmp_source = sources["fmp"]
    total = len(companies)
    country_label = f" ({country_filter.upper()})" if country_filter else ""
    typer.echo(f"FMP Preload: {total} companies{country_label}, concurrency={concurrency}")

    sem = __import__("asyncio").Semaphore(concurrency)
    fetched = 0
    skipped = 0
    failed = 0
    start_time = time.monotonic()

    async with httpx.AsyncClient() as client:
        async def _process(idx: int, company: Company) -> None:
            nonlocal fetched, skipped, failed
            t0 = time.monotonic()
            logs: list[str] = []

            async with sem:
                try:
                    async with session_factory() as db:
                        ids = await ingest_fmp_fundamentals_for_company(
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

                    elapsed = time.monotonic() - t0
                    # Detect if it was skipped (fresh) from logs
                    was_skipped = any("skipped" in l.lower() for l in logs)
                    if was_skipped:
                        skipped += 1
                        typer.echo(f"[{idx:>{len(str(total))}}/{total}] {company.ticker}: skipped (fresh)")
                    else:
                        fetched += 1
                        # Count series from logs
                        series_lines = [l for l in logs if "annual values" in l]
                        series_count = len(series_lines)
                        year_counts = []
                        for l in series_lines:
                            parts = l.strip().split(":")
                            if len(parts) >= 2:
                                num = parts[1].strip().split()[0]
                                try:
                                    year_counts.append(int(num))
                                except ValueError:
                                    pass
                        max_years = max(year_counts) if year_counts else 0
                        typer.echo(
                            f"[{idx:>{len(str(total))}}/{total}] {company.ticker}: "
                            f"{series_count} series, {max_years} years ({elapsed:.1f}s)"
                        )
                except Exception as e:
                    failed += 1
                    typer.echo(f"[{idx:>{len(str(total))}}/{total}] {company.ticker}: FAILED ({e})")

        # Process all companies concurrently (bounded by semaphore)
        tasks = [_process(i, c) for i, c in enumerate(companies, 1)]
        await __import__("asyncio").gather(*tasks)

    elapsed_total = time.monotonic() - start_time
    minutes = int(elapsed_total // 60)
    seconds = int(elapsed_total % 60)
    typer.echo(f"\nDone: {fetched} fetched, {skipped} skipped (fresh), {failed} failed in {minutes}m {seconds}s")

    await dispose_engine()


@app_cli.command()
def sync_prices(
    concurrency: int = typer.Option(5, help="Max parallel price fetches"),
    country: Optional[str] = typer.Option(None, help="Filter by country ISO2 code"),
    force: bool = typer.Option(False, help="Re-fetch even if data is fresh"),
):
    """Sync stock prices for all companies and country indices.

    Uses yfinance with 4-hour freshness windows. Safe to run frequently —
    fresh data is skipped automatically.

    Can be run from cron, e.g.:
        0 */4 * * * cd /path/to/invest-agent && .venv/bin/python -m app.cli sync-prices
    """
    import asyncio
    asyncio.run(_sync_prices_async(concurrency, country, force))


@app_cli.command()
def sync_macro(
    scope: str = typer.Option("monthly", help="Scope: 'daily' (FRED+market) or 'monthly' (all sources)"),
    force: bool = typer.Option(False, help="Re-fetch even if data is fresh"),
):
    """Sync country-level macro data.

    - daily: FRED rates/spreads + country index prices
    - monthly: All sources (World Bank, IMF, FRED, GDELT, market)

    Can be run from cron, e.g.:
        0 6 * * * cd /path/to/invest-agent && .venv/bin/python -m app.cli sync-macro --scope daily
        0 3 1 * * cd /path/to/invest-agent && .venv/bin/python -m app.cli sync-macro --scope monthly
    """
    import asyncio
    asyncio.run(_sync_macro_async(scope, force))


@app_cli.command()
def score_all(
    country: Optional[str] = typer.Option(None, help="Filter by country ISO2 code"),
    force: bool = typer.Option(False, help="Re-score all, not just stale companies"),
):
    """Score all companies with stale or missing scores.

    Scoring-only — no data ingestion. Run after sync-prices / preload-fmp
    to ensure underlying data is fresh.

    Can be run from cron, e.g.:
        0 6 * * 0 cd /path/to/invest-agent && .venv/bin/python -m app.cli score-all
    """
    import asyncio
    asyncio.run(_score_all_async(country, force))


@app_cli.command()
def discover_companies(
    min_market_cap: int = typer.Option(100_000_000, help="Minimum market cap in USD"),
):
    """Discover and add newly listed companies from FMP screener.

    Scans all major exchanges, deduplicates against existing companies,
    and inserts new ones.

    Can be run from cron, e.g.:
        0 2 1 * * cd /path/to/invest-agent && .venv/bin/python -m app.cli discover-companies
    """
    import asyncio
    asyncio.run(_discover_companies_async(min_market_cap))


@app_cli.command()
def export_training(
    output_dir: str = typer.Option("data/exports", help="Output directory for Parquet files"),
    include_prices: bool = typer.Option(False, help="Also export daily price series"),
    min_years: int = typer.Option(2, help="Minimum fiscal years of data per company"),
    countries: Optional[str] = typer.Option(None, help="Filter by country ISO2 codes (comma-separated)"),
):
    """Export comprehensive ML training dataset as Parquet.

    Reads raw FMP artefact JSON files and price history to produce a
    training-ready dataset with ~200 features per company per fiscal year.

    Usage:
        python -m app.cli export-training
        python -m app.cli export-training --countries US,GB --include-prices
    """
    import asyncio

    country_list = [c.strip().upper() for c in countries.split(",")] if countries else None
    asyncio.run(_export_training_async(output_dir, include_prices, min_years, country_list))


async def _export_training_async(
    output_dir: str,
    include_prices: bool,
    min_years: int,
    countries: list[str] | None,
) -> None:
    """Async implementation of export_training."""
    from app.db.session import _get_session_factory, dispose_engine
    from app.export.training_dataset import export_training_dataset

    session_factory = _get_session_factory()

    await export_training_dataset(
        session_factory=session_factory,
        output_dir=output_dir,
        include_prices=include_prices,
        min_years=min_years,
        countries=countries,
        log_fn=typer.echo,
    )

    await dispose_engine()


async def _sync_prices_async(
    concurrency: int,
    country_filter: str | None,
    force: bool,
) -> None:
    """Async implementation of sync_prices CLI command.

    Uses FMP for company stock prices (JSONB storage) and yfinance for country indices.
    """
    import json
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    import httpx
    from sqlalchemy import select

    from app.config import get_settings
    from app.db.models import Company, Country
    from app.db.session import _get_session_factory, dispose_engine
    from app.ingest.artefact_store import ArtefactStore
    from app.ingest.fmp_prices import ingest_fmp_prices_for_company
    from app.ingest.marketdata import ingest_market_data_for_country
    from app.ingest.seed_sources import seed_data_sources

    settings = get_settings()
    session_factory = _get_session_factory()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)
    fmp_api_key = settings.fmp_api_key

    today = datetime.now(tz=timezone.utc).date()
    as_of = today.replace(day=1)
    market_start = f"{as_of.year - 2}-01-01"
    market_end = str(today)

    typer.echo(f"Price Sync: concurrency={concurrency}")

    async with session_factory() as db:
        sources = await seed_data_sources(db)
        await db.commit()
        fmp_source = sources.get("fmp")

        # Country indices (yfinance — index tickers)
        config_path = Path(__file__).resolve().parents[1] / "config" / "investable_countries_v1.json"
        country_config = json.loads(config_path.read_text())

        typer.echo("\n=== Country Indices ===")
        for cc in country_config["countries"]:
            result = await db.execute(select(Country).where(Country.iso2 == cc["iso2"]))
            country = result.scalar_one_or_none()
            if country:
                try:
                    await ingest_market_data_for_country(
                        db=db, artefact_store=artefact_store,
                        yf_source=sources["yfinance"], country=country,
                        start_date=market_start, end_date=market_end,
                        log_fn=typer.echo, force=force,
                    )
                    await db.commit()
                except Exception as e:
                    typer.echo(f"  {cc['iso2']}: FAILED ({e})")

        # Company prices via FMP
        query = select(Company).order_by(Company.ticker)
        if country_filter:
            query = query.where(Company.country_iso2 == country_filter.upper())
        result = await db.execute(query)
        companies = list(result.scalars().all())

    total = len(companies)
    typer.echo(f"\n=== Company Prices ({total} companies, FMP → JSONB) ===")

    if not fmp_api_key:
        typer.echo("FMP_API_KEY not set, skipping company prices.")
        await dispose_engine()
        return

    import asyncio
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
                        await ingest_fmp_prices_for_company(
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
                        typer.echo(f"[{idx}/{total}] fetched={fetched} no_data={no_data} failed={failed} ({elapsed:.0f}s, {rate:.1f}/s, ETA ~{eta_min}m)")
                except Exception as e:
                    failed += 1
                    if failed <= 10:
                        typer.echo(f"[{idx}/{total}] {company.ticker}: FAILED ({e})")

        tasks = [_process(i, c) for i, c in enumerate(companies, 1)]
        await asyncio.gather(*tasks)

    elapsed = time.monotonic() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    typer.echo(f"\nDone: {fetched} fetched, {skipped} skipped, {no_data} no_data, {failed} failed in {minutes}m {seconds}s")
    await dispose_engine()


async def _sync_macro_async(scope: str, force: bool) -> None:
    """Async implementation of sync_macro CLI command."""
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    from sqlalchemy import select

    from app.config import get_settings
    from app.db.models import Country
    from app.db.session import _get_session_factory, dispose_engine
    from app.ingest.artefact_store import ArtefactStore
    from app.ingest.fred import ingest_fred_for_country
    from app.ingest.gdelt import ingest_gdelt_stability
    from app.ingest.imf import ingest_imf_for_country
    from app.ingest.marketdata import ingest_market_data_for_country
    from app.ingest.seed_sources import seed_data_sources
    from app.ingest.world_bank import ingest_world_bank_for_country

    settings = get_settings()
    session_factory = _get_session_factory()
    artefact_store = ArtefactStore(settings.artefact_storage_dir)

    today = datetime.now(tz=timezone.utc).date()
    as_of = today.replace(day=1)
    end_year = as_of.year
    start_year = 2015
    market_start = f"{end_year - 2}-01-01"
    market_end = str(as_of)
    fred_start = f"{end_year - 2}-01-01"
    fred_end = str(as_of)

    typer.echo(f"Macro Sync: scope={scope}, as_of={as_of}, force={force}")

    config_path = Path(__file__).resolve().parents[1] / "config" / "investable_countries_v1.json"
    country_config = json.loads(config_path.read_text())
    countries_cfg = country_config["countries"]
    wb_indicators = country_config["world_bank_indicators"]
    imf_indicators = country_config.get("imf_indicators", {})
    fred_series = country_config["fred_series"]

    async with session_factory() as db:
        sources = await seed_data_sources(db)
        await db.commit()

        countries: list[Country] = []
        for cc in countries_cfg:
            result = await db.execute(select(Country).where(Country.iso2 == cc["iso2"]))
            country = result.scalar_one_or_none()
            if country is None:
                country = Country(
                    iso2=cc["iso2"], iso3=cc["iso3"],
                    name=cc["name"], equity_index_symbol=cc["equity_index_symbol"],
                )
                db.add(country)
                await db.flush()
            countries.append(country)
        await db.commit()

        for country in countries:
            typer.echo(f"\n--- {country.name} ({country.iso2}) ---")

            if scope == "monthly":
                await ingest_world_bank_for_country(
                    db=db, artefact_store=artefact_store,
                    wb_source=sources["world_bank"], country=country,
                    indicators=wb_indicators, start_year=start_year,
                    end_year=end_year, log_fn=typer.echo, force=force,
                )
                if imf_indicators:
                    await ingest_imf_for_country(
                        db=db, artefact_store=artefact_store,
                        imf_source=sources["imf"], country=country,
                        indicators=imf_indicators, start_year=start_year,
                        end_year=end_year, log_fn=typer.echo, force=force,
                    )

            await ingest_fred_for_country(
                db=db, artefact_store=artefact_store,
                fred_source=sources["fred"], country=country,
                fred_series=fred_series, api_key=settings.fred_api_key,
                start_date=fred_start, end_date=fred_end,
                log_fn=typer.echo, force=force,
            )

            await ingest_market_data_for_country(
                db=db, artefact_store=artefact_store,
                yf_source=sources["yfinance"], country=country,
                start_date=market_start, end_date=market_end,
                log_fn=typer.echo, force=force,
            )

            if scope == "monthly":
                await ingest_gdelt_stability(
                    db=db, artefact_store=artefact_store,
                    gdelt_source=sources["gdelt"], country=country,
                    as_of=as_of, log_fn=typer.echo, force=force,
                )

            await db.commit()

    typer.echo(f"\nMacro Sync ({scope}) complete.")
    await dispose_engine()


async def _score_all_async(country_filter: str | None, force: bool) -> None:
    """Async implementation of score_all CLI command."""
    import time
    from datetime import datetime, timezone

    from sqlalchemy import select, delete

    from app.db.models import Company, CompanyRiskRegister, CompanyScore
    from app.db.session import _get_session_factory, dispose_engine
    from app.packets.company_packets import build_company_packet
    from app.score.company import compute_company_scores, detect_company_risks
    from app.score.versions import COMPANY_CALC_VERSION

    session_factory = _get_session_factory()
    today = datetime.now(tz=timezone.utc).date()
    as_of = today.replace(day=1)
    batch_size = 500

    typer.echo(f"Score All: as_of={as_of}, force={force}")
    start_time = time.monotonic()

    async with session_factory() as db:
        query = select(Company).order_by(Company.ticker)
        if country_filter:
            query = query.where(Company.country_iso2 == country_filter.upper())
        result = await db.execute(query)
        all_companies = list(result.scalars().all())

        if force:
            companies_to_score = all_companies
        else:
            result = await db.execute(
                select(CompanyScore.company_id).where(
                    CompanyScore.as_of == as_of,
                    CompanyScore.calc_version == COMPANY_CALC_VERSION,
                )
            )
            scored_ids = {row[0] for row in result.all()}
            companies_to_score = [c for c in all_companies if c.id not in scored_ids]

        total = len(companies_to_score)
        typer.echo(f"Companies to score: {total} (of {len(all_companies)} total)")

        if not companies_to_score:
            typer.echo("All companies already scored.")
            await dispose_engine()
            return

        all_scores: list[CompanyScore] = []
        all_risks: dict[str, list[CompanyRiskRegister]] = {}

        for batch_start in range(0, total, batch_size):
            batch = companies_to_score[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size

            typer.echo(f"\n--- Batch {batch_num}/{total_batches}: {len(batch)} companies ---")

            scores = await compute_company_scores(
                db=db, companies=batch, as_of=as_of, log_fn=typer.echo,
            )

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

            for score in scores:
                company = next(c for c in batch if c.id == score.company_id)
                await db.execute(
                    delete(CompanyRiskRegister).where(
                        CompanyRiskRegister.company_id == company.id,
                        CompanyRiskRegister.detected_at == as_of,
                    )
                )
                risks = detect_company_risks(None, company, score, as_of, typer.echo)
                for r in risks:
                    db.add(r)
                all_risks[company.ticker] = risks
            await db.flush()

            all_scores.extend(scores)
            await db.commit()
            typer.echo(f"  Batch {batch_num}: {len(scores)} scored")

        # Build packets
        typer.echo(f"\n--- Building Packets ---")
        result = await db.execute(
            select(CompanyScore).where(
                CompanyScore.as_of == as_of,
                CompanyScore.calc_version == COMPANY_CALC_VERSION,
            )
        )
        global_scores = list(result.scalars().all())

        for score in all_scores:
            company = next(c for c in companies_to_score if c.id == score.company_id)
            risks = all_risks.get(company.ticker, [])
            await build_company_packet(
                db=db, company=company, score=score, risks=risks,
                all_scores=global_scores, include_evidence=True,
            )
        await db.commit()

    elapsed = time.monotonic() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    typer.echo(f"\nDone: {len(all_scores)} scored in {minutes}m {seconds}s")
    await dispose_engine()


async def _discover_companies_async(min_market_cap: int) -> None:
    """Async implementation of discover_companies CLI command."""
    import httpx
    from sqlalchemy import select

    from app.config import get_settings
    from app.db.models import Company
    from app.db.session import _get_session_factory, dispose_engine
    from app.ingest.company_lookup import SECTOR_TO_GICS

    settings = get_settings()
    if not settings.fmp_api_key:
        typer.echo("ERROR: FMP_API_KEY not configured")
        raise typer.Exit(1)

    session_factory = _get_session_factory()

    exchanges = [
        "NYSE", "NASDAQ", "AMEX", "LSE", "TSX", "JPX", "HKSE", "ASX",
        "BSE", "NSE", "SHH", "SHZ", "KSC", "KOE", "SES", "SET", "TAI",
        "TWO", "PAR", "AMS", "MIL", "BME", "XETRA", "SIX", "STO", "OSL",
        "HEL", "CPH", "BRU", "SAO", "JNB", "TLV", "IST", "SAU", "WSE",
        "NZE", "BUD", "ATH", "VIE", "PRA", "JKT", "KLS", "MEX",
        "TSXV", "NEO", "CNQ", "OTC", "PNK", "LIS", "DUB",
        "FSX", "BER", "MUN", "STU", "HAM", "DUS",
        "IOB", "BUE", "KUW", "DFM", "DOH", "SGO", "BVC", "EGX",
        "HOSE", "ICE", "MCX", "RIS", "TAL",
    ]

    async with session_factory() as db:
        result = await db.execute(select(Company.ticker))
        existing_tickers = {row[0] for row in result.all()}

    typer.echo(f"Discover: min_market_cap=${min_market_cap/1e6:.0f}M, {len(exchanges)} exchanges")
    typer.echo(f"Existing: {len(existing_tickers)} companies")

    total_added = 0
    seen_tickers = set(existing_tickers)

    async with httpx.AsyncClient() as client:
        for exchange in exchanges:
            try:
                resp = await client.get(
                    "https://financialmodelingprep.com/stable/company-screener",
                    params={
                        "apikey": settings.fmp_api_key,
                        "exchange": exchange,
                        "limit": 5000,
                        "marketCapMoreThan": min_market_cap,
                        "isEtf": False,
                        "isFund": False,
                        "isActivelyTrading": True,
                    },
                    timeout=60,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not isinstance(data, list):
                    continue
            except Exception as e:
                typer.echo(f"  {exchange}: FAILED ({e})")
                continue

            new_in_exchange: list[Company] = []
            for item in data:
                ticker = item.get("symbol", "")
                if not ticker or ticker in seen_tickers:
                    continue
                seen_tickers.add(ticker)

                sector = item.get("sector", "")
                gics = SECTOR_TO_GICS.get(sector.lower().strip(), "") if sector else ""
                country_iso2 = item.get("country") or "US"
                name = item.get("companyName") or ticker

                new_in_exchange.append(Company(
                    ticker=ticker, cik=None, name=name[:200],
                    gics_code=gics, country_iso2=country_iso2,
                    config_version="fmp_screener",
                ))

            if new_in_exchange:
                async with session_factory() as db:
                    for c in new_in_exchange:
                        db.add(c)
                    await db.commit()
                total_added += len(new_in_exchange)
                typer.echo(f"  {exchange:10s} +{len(new_in_exchange):>5d} new")

    typer.echo(f"\nDone: {total_added} new companies. Total: {len(seen_tickers)}")
    await dispose_engine()


async def _add_companies_async(
    count: int,
    min_market_cap: int,
    country_filter: str | None,
    preload: bool,
    concurrency: int,
) -> None:
    """Async implementation of add_companies."""
    import httpx
    from sqlalchemy import select

    from app.config import get_settings
    from app.db.models import Company
    from app.db.session import _get_session_factory, dispose_engine
    from app.ingest.company_lookup import SECTOR_TO_GICS

    settings = get_settings()
    if not settings.fmp_api_key:
        typer.echo("ERROR: FMP_API_KEY not configured in .env")
        raise typer.Exit(1)

    session_factory = _get_session_factory()

    # Phase 1: Discover companies via FMP screener
    typer.echo(f"Fetching companies from FMP screener (min market cap: ${min_market_cap/1e9:.0f}B)...")

    params: dict = {
        "apikey": settings.fmp_api_key,
        "limit": 5000,  # fetch max to account for existing companies in DB
        "marketCapMoreThan": min_market_cap,
        "isEtf": False,
        "isFund": False,
        "isActivelyTrading": True,
    }
    if country_filter:
        params["country"] = country_filter.upper()

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://financialmodelingprep.com/stable/company-screener",
            params=params,
            timeout=60,
        )
        resp.raise_for_status()
        screener_data = resp.json()

    if not isinstance(screener_data, list):
        typer.echo(f"ERROR: Unexpected response from FMP screener: {screener_data}")
        raise typer.Exit(1)

    typer.echo(f"FMP screener returned {len(screener_data)} companies")

    # Phase 2: Filter and insert new companies
    async with session_factory() as db:
        result = await db.execute(select(Company.ticker))
        existing_tickers = {row[0] for row in result.all()}
        typer.echo(f"Existing companies in DB: {len(existing_tickers)}")

        added = 0
        skipped_existing = 0
        new_companies: list[Company] = []

        for item in screener_data:
            if added >= count:
                break

            ticker = item.get("symbol", "")
            if not ticker or ticker in existing_tickers:
                skipped_existing += 1
                continue

            # Avoid adding a ticker we're about to add (duplicates in screener)
            if any(c.ticker == ticker for c in new_companies):
                continue

            sector = item.get("sector", "")
            gics = SECTOR_TO_GICS.get(sector.lower().strip(), "") if sector else ""
            country_iso2 = item.get("country") or "US"
            name = item.get("companyName") or ticker
            market_cap = item.get("marketCap", 0)

            company = Company(
                ticker=ticker,
                cik=None,
                name=name[:200],
                gics_code=gics,
                country_iso2=country_iso2,
                config_version="fmp_screener",
            )
            db.add(company)
            new_companies.append(company)
            added += 1

            cap_b = market_cap / 1e9
            typer.echo(f"  + {ticker:12s} {country_iso2:4s} {gics or '??':4s} ${cap_b:>8.1f}B  {name[:45]}")

        await db.commit()

    typer.echo(f"\nAdded {len(new_companies)} new companies ({skipped_existing} already existed)")

    if not new_companies:
        typer.echo("No new companies to add.")
        await dispose_engine()
        return

    # Phase 3: Optionally preload FMP fundamentals
    if preload and new_companies:
        typer.echo(f"\nPreloading FMP fundamentals for {len(new_companies)} new companies...")
        await _preload_fmp_async(concurrency=concurrency, force=False, country_filter=None)

    await dispose_engine()
