"""SEC company tickers cache and yfinance enrichment for company search."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from functools import partial

import httpx

logger = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_USER_AGENT = "InvestAgent/1.0 (admin@investagent.app)"
_CACHE_TTL_SECONDS = 86400  # 24 hours

# Maps yfinance sector text (lowercased) → our 2-digit GICS code.
SECTOR_TO_GICS: dict[str, str] = {
    "energy": "10",
    "basic materials": "15",
    "materials": "15",
    "industrials": "20",
    "consumer cyclical": "25",
    "consumer discretionary": "25",
    "consumer defensive": "30",
    "consumer staples": "30",
    "healthcare": "35",
    "health care": "35",
    "financial services": "40",
    "financials": "40",
    "financial": "40",
    "technology": "45",
    "information technology": "45",
    "communication services": "50",
    "utilities": "55",
    "real estate": "60",
}

# Maps yfinance country name → ISO2 code.
COUNTRY_TO_ISO2: dict[str, str] = {
    "United States": "US",
    "United Kingdom": "GB",
    "Japan": "JP",
    "Canada": "CA",
    "Australia": "AU",
    "Germany": "DE",
    "France": "FR",
    "Switzerland": "CH",
    "Sweden": "SE",
    "Netherlands": "NL",
}


@dataclass
class SECCompanyEntry:
    cik: str  # zero-padded to 10 digits
    ticker: str
    name: str


class SECTickerCache:
    """In-memory cache for the SEC company_tickers.json (~13K US public companies)."""

    _entries: list[SECCompanyEntry] = []
    _by_ticker: dict[str, SECCompanyEntry] = {}
    _fetched_at: float = 0.0
    _lock: asyncio.Lock | None = None

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    async def get_entries(cls) -> list[SECCompanyEntry]:
        """Return cached entries, refreshing if stale."""
        if time.time() - cls._fetched_at > _CACHE_TTL_SECONDS or not cls._entries:
            async with cls._get_lock():
                if time.time() - cls._fetched_at > _CACHE_TTL_SECONDS or not cls._entries:
                    await cls._refresh()
        return cls._entries

    @classmethod
    async def lookup_cik(cls, ticker: str) -> str | None:
        """Look up CIK for a ticker. Returns zero-padded 10-digit CIK or None."""
        await cls.get_entries()
        entry = cls._by_ticker.get(ticker.upper())
        return entry.cik if entry else None

    @classmethod
    async def search(cls, query: str, limit: int = 20) -> list[SECCompanyEntry]:
        """Search by ticker prefix or name substring (case-insensitive)."""
        await cls.get_entries()
        q = query.upper().strip()
        if not q:
            return []

        results: list[SECCompanyEntry] = []
        seen: set[str] = set()

        # Exact ticker match first
        if q in cls._by_ticker:
            results.append(cls._by_ticker[q])
            seen.add(q)

        # Ticker prefix matches
        for e in cls._entries:
            if len(results) >= limit:
                break
            if e.ticker.startswith(q) and e.ticker not in seen:
                results.append(e)
                seen.add(e.ticker)

        # Name substring matches
        for e in cls._entries:
            if len(results) >= limit:
                break
            if q in e.name.upper() and e.ticker not in seen:
                results.append(e)
                seen.add(e.ticker)

        return results[:limit]

    @classmethod
    async def _refresh(cls) -> None:
        """Fetch and parse SEC company_tickers.json."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _TICKERS_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

        entries: list[SECCompanyEntry] = []
        by_ticker: dict[str, SECCompanyEntry] = {}
        for item in data.values():
            cik_str = str(item["cik_str"]).zfill(10)
            ticker = item["ticker"].upper()
            entry = SECCompanyEntry(
                cik=cik_str,
                ticker=ticker,
                name=item["title"],
            )
            entries.append(entry)
            by_ticker[ticker] = entry

        cls._entries = entries
        cls._by_ticker = by_ticker
        cls._fetched_at = time.time()
        logger.info("SEC ticker cache refreshed: %d entries", len(entries))


def enrich_with_yfinance(ticker: str) -> dict | None:
    """Fetch metadata from yfinance for a single ticker (synchronous).

    Returns dict with keys: market_cap, sector, country, name.
    Returns None on failure.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        if not info.get("longName") and not info.get("shortName"):
            return None
        return {
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "country": info.get("country"),
            "name": info.get("longName") or info.get("shortName"),
        }
    except Exception:
        return None


async def enrich_with_yfinance_async(ticker: str) -> dict | None:
    """Async wrapper for enrich_with_yfinance."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(enrich_with_yfinance, ticker))


def map_sector_to_gics(sector_text: str | None) -> str:
    """Map yfinance sector name to our 2-digit GICS code. Returns '' if unknown."""
    if not sector_text:
        return ""
    return SECTOR_TO_GICS.get(sector_text.lower().strip(), "")


def map_country_to_iso2(country_name: str | None) -> str:
    """Map yfinance country name to ISO2 code. Defaults to 'US'."""
    if not country_name:
        return "US"
    return COUNTRY_TO_ISO2.get(country_name, "US")
