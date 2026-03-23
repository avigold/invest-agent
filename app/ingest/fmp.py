"""Financial Modeling Prep (FMP) API client.

Provides async functions to fetch financial statements from the FMP stable API.
All requests go through a shared rate limiter to stay within FMP's per-minute
limits and automatically retry on 429 Too Many Requests.
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx

_BASE_URL = "https://financialmodelingprep.com/stable"

# ── Rate limiter ─────────────────────────────────────────────────────────

_MAX_RETRIES = 3
_BACKOFF_BASE = 2  # seconds — retries wait 2s, 4s, 8s


class FMPRateLimiter:
    """Token-bucket rate limiter for FMP API calls.

    Enforces a maximum request rate (default 5/s) across all concurrent
    callers in the same process. Thread-safe within a single event loop.
    """

    def __init__(self, max_per_second: float = 5.0):
        self._interval = 1.0 / max_per_second
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


# Module-level singleton — created lazily to pick up config at runtime
_rate_limiter: FMPRateLimiter | None = None


def _get_limiter() -> FMPRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        try:
            from app.config import get_settings
            rate = get_settings().fmp_rate_limit
        except Exception:
            rate = 5.0
        _rate_limiter = FMPRateLimiter(max_per_second=rate)
    return _rate_limiter


async def _fmp_get(
    client: httpx.AsyncClient,
    path: str,
    params: dict,
    timeout: float = 30,
) -> httpx.Response:
    """Rate-limited FMP GET request with automatic 429 retry.

    Acquires a rate-limit token before each attempt. On 429, waits with
    exponential backoff (2s, 4s, 8s) before retrying up to 3 times.
    """
    limiter = _get_limiter()
    url = f"{_BASE_URL}{path}"

    for attempt in range(_MAX_RETRIES + 1):
        await limiter.acquire()
        resp = await client.get(url, params=params, timeout=timeout)
        if resp.status_code == 429:
            if attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** (attempt + 1)
                await asyncio.sleep(wait)
                continue
        resp.raise_for_status()
        return resp

    # Should not reach here, but satisfy type checker
    resp.raise_for_status()
    return resp  # type: ignore[return-value]


# ── Public API functions ─────────────────────────────────────────────────


async def fetch_income_statement(
    client: httpx.AsyncClient,
    symbol: str,
    api_key: str,
    limit: int = 50,
) -> tuple[list[dict], str]:
    """Fetch annual income statements.

    Returns (parsed JSON array, raw response text).
    """
    resp = await _fmp_get(
        client, "/income-statement",
        {"symbol": symbol, "limit": limit, "period": "annual", "apikey": api_key},
    )
    raw = resp.text
    data = resp.json()
    if not isinstance(data, list):
        return [], raw
    return data, raw


async def fetch_balance_sheet(
    client: httpx.AsyncClient,
    symbol: str,
    api_key: str,
    limit: int = 50,
) -> tuple[list[dict], str]:
    """Fetch annual balance sheet statements.

    Returns (parsed JSON array, raw response text).
    """
    resp = await _fmp_get(
        client, "/balance-sheet-statement",
        {"symbol": symbol, "limit": limit, "period": "annual", "apikey": api_key},
    )
    raw = resp.text
    data = resp.json()
    if not isinstance(data, list):
        return [], raw
    return data, raw


async def fetch_cash_flow(
    client: httpx.AsyncClient,
    symbol: str,
    api_key: str,
    limit: int = 50,
) -> tuple[list[dict], str]:
    """Fetch annual cash flow statements.

    Returns (parsed JSON array, raw response text).
    """
    resp = await _fmp_get(
        client, "/cash-flow-statement",
        {"symbol": symbol, "limit": limit, "period": "annual", "apikey": api_key},
    )
    raw = resp.text
    data = resp.json()
    if not isinstance(data, list):
        return [], raw
    return data, raw


async def fetch_profile(
    client: httpx.AsyncClient,
    symbol: str,
    api_key: str,
) -> dict | None:
    """Fetch company profile from FMP.

    Returns dict with keys: isAdr, exchangeShortName, isin, mktCap, country,
    or None if the symbol is not found.
    """
    resp = await _fmp_get(
        client, "/profile",
        {"symbol": symbol, "apikey": api_key},
    )
    data = resp.json()
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict) and data:
        return data
    return None


async def fetch_historical_prices(
    client: httpx.AsyncClient,
    symbol: str,
    api_key: str,
    from_date: str = "1970-01-01",
    to_date: str | None = None,
) -> tuple[list[dict], str]:
    """Fetch full daily price history via the light EOD endpoint.

    Automatically paginates if the ticker has more than 5,000 trading days
    of history (only applies to pre-~2006 IPOs).

    Returns (list of {date, price, volume} dicts sorted oldest-first, raw JSON text).
    """
    all_rows: list[dict] = []
    current_to = to_date or "2099-12-31"

    # Paginate by date window — FMP caps at 5,000 rows per call
    for _ in range(5):  # max 5 pages = 25,000 trading days (~100 years)
        resp = await _fmp_get(
            client, "/historical-price-eod/light",
            {"symbol": symbol, "apikey": api_key, "from": from_date, "to": current_to},
        )
        data = resp.json()
        if not isinstance(data, list) or not data:
            break

        all_rows.extend(data)

        # FMP returns newest-first; if we got fewer than 5000, we have everything
        if len(data) < 5000:
            break

        # Next page: fetch everything before the oldest date in this batch
        oldest_date = data[-1]["date"]
        from datetime import datetime, timedelta
        oldest_dt = datetime.strptime(oldest_date, "%Y-%m-%d") - timedelta(days=1)
        current_to = oldest_dt.strftime("%Y-%m-%d")

    # Sort oldest-first for consistent storage
    all_rows.sort(key=lambda r: r["date"])

    raw = json.dumps(all_rows)
    return all_rows, raw
