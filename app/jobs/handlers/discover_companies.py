"""Discover companies handler: find newly listed companies via FMP screener.

Iterates FMP screener per-exchange to bypass the 5,000 single-call cap,
deduplicates against existing tickers in the database, and inserts new ones.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Company
from app.ingest.company_lookup import SECTOR_TO_GICS

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob

# Major exchanges to scan — covers ~99% of FMP's actively traded universe.
_EXCHANGES = [
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


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def discover_companies_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Discover and add newly listed companies from FMP screener.

    Params:
        min_market_cap: Minimum market cap in USD (default: 100,000,000).
        exchanges: List of exchange codes to scan (default: all major).
    """
    settings = get_settings()
    min_market_cap = job.params.get("min_market_cap", 100_000_000)
    exchanges = job.params.get("exchanges", _EXCHANGES)

    if not settings.fmp_api_key:
        _log(job, "ERROR: FMP_API_KEY not configured")
        return

    _log(job, f"Discover Companies: min_market_cap=${min_market_cap/1e6:.0f}M, {len(exchanges)} exchanges")

    # Get existing tickers
    async with session_factory() as db:
        result = await db.execute(select(Company.ticker))
        existing_tickers = {row[0] for row in result.all()}

    _log(job, f"Existing companies: {len(existing_tickers)}")

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
                    _log(job, f"  {exchange}: HTTP {resp.status_code}")
                    continue

                data = resp.json()
                if not isinstance(data, list):
                    continue

            except Exception as e:
                _log(job, f"  {exchange}: FAILED ({e})")
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
                    ticker=ticker,
                    cik=None,
                    name=name[:200],
                    gics_code=gics,
                    country_iso2=country_iso2,
                    config_version="fmp_screener",
                ))

            if new_in_exchange:
                async with session_factory() as db:
                    for c in new_in_exchange:
                        db.add(c)
                    await db.commit()
                total_added += len(new_in_exchange)
                _log(job, f"  {exchange}: +{len(new_in_exchange)} new")
            # Silent for exchanges with nothing new

    _log(job, f"\nDiscover complete: {total_added} new companies added. Total: {len(seen_tickers)}")
