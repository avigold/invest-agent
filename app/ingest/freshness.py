"""Data freshness configuration — staleness windows per source."""
from __future__ import annotations

from datetime import datetime, timezone

# How many hours before each source's data is considered stale.
# Within this window, re-fetching is skipped (unless force=True).
FRESHNESS_HOURS: dict[str, int] = {
    "world_bank": 720,              # 30 days (annual data)
    "imf_weo": 720,                 # 30 days (annual data)
    "fred": 24,                     # 1 day (daily/monthly series)
    "yfinance_market": 4,           # 4 hours (market data)
    "gdelt": 168,                   # 7 days (monthly aggregation)
    "sec_edgar": 720,               # 30 days (annual filings)
    "yfinance_fundamentals": 720,   # 30 days (annual filings)
    "fmp_fundamentals": 720,         # 30 days (annual filings)
}


def is_stale(source_name: str, fetched_at: datetime) -> bool:
    """Check if data from a source is stale based on its freshness window."""
    max_hours = FRESHNESS_HOURS.get(source_name)
    if max_hours is None:
        return True  # Unknown source — always fetch

    now = datetime.now(timezone.utc)
    # Make fetched_at timezone-aware if it isn't
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)

    age_hours = (now - fetched_at).total_seconds() / 3600
    return age_hours > max_hours
