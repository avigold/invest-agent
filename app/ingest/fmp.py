"""Financial Modeling Prep (FMP) API client.

Provides async functions to fetch financial statements from the FMP stable API.
"""
from __future__ import annotations

import httpx

_BASE_URL = "https://financialmodelingprep.com/stable"


async def fetch_income_statement(
    client: httpx.AsyncClient,
    symbol: str,
    api_key: str,
    limit: int = 50,
) -> tuple[list[dict], str]:
    """Fetch annual income statements.

    Returns (parsed JSON array, raw response text).
    """
    url = f"{_BASE_URL}/income-statement"
    params = {"symbol": symbol, "limit": limit, "period": "annual", "apikey": api_key}
    resp = await client.get(url, params=params, timeout=30)
    resp.raise_for_status()
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
    url = f"{_BASE_URL}/balance-sheet-statement"
    params = {"symbol": symbol, "limit": limit, "period": "annual", "apikey": api_key}
    resp = await client.get(url, params=params, timeout=30)
    resp.raise_for_status()
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
    url = f"{_BASE_URL}/cash-flow-statement"
    params = {"symbol": symbol, "limit": limit, "period": "annual", "apikey": api_key}
    resp = await client.get(url, params=params, timeout=30)
    resp.raise_for_status()
    raw = resp.text
    data = resp.json()
    if not isinstance(data, list):
        return [], raw
    return data, raw


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
    url = f"{_BASE_URL}/historical-price-eod/light"
    all_rows: list[dict] = []
    current_to = to_date or "2099-12-31"

    # Paginate by date window — FMP caps at 5,000 rows per call
    for _ in range(5):  # max 5 pages = 25,000 trading days (~100 years)
        params = {
            "symbol": symbol,
            "apikey": api_key,
            "from": from_date,
            "to": current_to,
        }
        resp = await client.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            break

        all_rows.extend(data)

        # FMP returns newest-first; if we got fewer than 5000, we have everything
        if len(data) < 5000:
            break

        # Next page: fetch everything before the oldest date in this batch
        oldest_date = data[-1]["date"]
        # Subtract one day to avoid overlap
        from datetime import datetime, timedelta
        oldest_dt = datetime.strptime(oldest_date, "%Y-%m-%d") - timedelta(days=1)
        current_to = oldest_dt.strftime("%Y-%m-%d")

    # Sort oldest-first for consistent storage
    all_rows.sort(key=lambda r: r["date"])

    # Build raw text for artefact storage
    import json
    raw = json.dumps(all_rows)

    return all_rows, raw
