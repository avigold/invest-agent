"""Exchange schedule and market status detection."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

EXCHANGE_SCHEDULES: dict[str, dict] = {
    "NYSE": {
        "tz": "America/New_York",
        "open": time(9, 30),
        "close": time(16, 0),
        "weekdays": {0, 1, 2, 3, 4},  # Mon-Fri
    },
}

COUNTRY_TO_EXCHANGE: dict[str, str] = {
    "US": "NYSE",
}


def get_market_status(country_iso2: str = "US") -> dict:
    """Return market open/closed status for the given country's primary exchange."""
    exchange = COUNTRY_TO_EXCHANGE.get(country_iso2, "NYSE")
    schedule = EXCHANGE_SCHEDULES[exchange]
    tz = ZoneInfo(schedule["tz"])
    now = datetime.now(tz)

    is_trading_day = now.weekday() in schedule["weekdays"]
    current_time = now.time()
    is_open = is_trading_day and schedule["open"] <= current_time < schedule["close"]

    # Compute last close time
    if is_trading_day and current_time >= schedule["close"]:
        last_close = now.replace(
            hour=schedule["close"].hour,
            minute=schedule["close"].minute,
            second=0,
            microsecond=0,
        )
    elif is_trading_day and current_time < schedule["open"]:
        # Before market open today — last close was previous trading day
        prev = _prev_trading_day(now, schedule["weekdays"])
        last_close = prev.replace(
            hour=schedule["close"].hour,
            minute=schedule["close"].minute,
            second=0,
            microsecond=0,
        )
    elif not is_trading_day:
        prev = _prev_trading_day(now, schedule["weekdays"])
        last_close = prev.replace(
            hour=schedule["close"].hour,
            minute=schedule["close"].minute,
            second=0,
            microsecond=0,
        )
    else:
        # Market is currently open — last close was the previous trading day
        prev = _prev_trading_day(now, schedule["weekdays"])
        last_close = prev.replace(
            hour=schedule["close"].hour,
            minute=schedule["close"].minute,
            second=0,
            microsecond=0,
        )

    # Compute next open time
    if is_open:
        # Already open — next open is tomorrow (or next trading day)
        nxt = _next_trading_day(now, schedule["weekdays"])
        next_open = nxt.replace(
            hour=schedule["open"].hour,
            minute=schedule["open"].minute,
            second=0,
            microsecond=0,
        )
    elif is_trading_day and current_time < schedule["open"]:
        next_open = now.replace(
            hour=schedule["open"].hour,
            minute=schedule["open"].minute,
            second=0,
            microsecond=0,
        )
    else:
        nxt = _next_trading_day(now, schedule["weekdays"])
        next_open = nxt.replace(
            hour=schedule["open"].hour,
            minute=schedule["open"].minute,
            second=0,
            microsecond=0,
        )

    return {
        "is_open": is_open,
        "exchange": exchange,
        "next_open": next_open.astimezone(timezone.utc).isoformat(),
        "last_close_time": last_close.astimezone(timezone.utc).isoformat(),
    }


def _prev_trading_day(dt: datetime, weekdays: set[int]) -> datetime:
    """Return the most recent trading day before dt."""
    d = dt - timedelta(days=1)
    while d.weekday() not in weekdays:
        d -= timedelta(days=1)
    return d


def _next_trading_day(dt: datetime, weekdays: set[int]) -> datetime:
    """Return the next trading day after dt."""
    d = dt + timedelta(days=1)
    while d.weekday() not in weekdays:
        d += timedelta(days=1)
    return d
