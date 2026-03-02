"""Compute rolling N-year returns and find stocks exceeding a threshold."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

import pandas as pd


@dataclass
class ReturnMatch:
    """A single window where a stock exceeded the return threshold."""

    ticker: str
    name: str
    country_iso2: str
    gics_code: str
    window_start: date
    window_end: date
    start_price: float
    end_price: float
    return_pct: float  # e.g. 3.0 for 300%


def find_threshold_windows(
    prices: dict[str, pd.Series],
    ticker_metadata: dict[str, dict],
    window_years: int,
    return_threshold: float,
    log_fn: Callable[[str], None] | None = None,
) -> list[ReturnMatch]:
    """Scan all tickers for rolling windows exceeding the return threshold.

    For each ticker, resample to month-end and slide an N-year window.
    Keep only the best (highest return) non-overlapping window per ticker.

    Args:
        prices: {ticker: pd.Series of daily close prices}
        ticker_metadata: {ticker: {name, country_iso2, gics_code}}
        window_years: rolling window size in years
        return_threshold: minimum return (e.g., 3.0 for 300% gain)

    Returns: list of ReturnMatch sorted by return_pct descending
    """
    log = log_fn or (lambda _: None)
    window_months = window_years * 12
    matches: list[ReturnMatch] = []

    for ticker, price_series in prices.items():
        # Resample to month-end for cleaner windows
        monthly = price_series.resample("ME").last().dropna()

        if len(monthly) < window_months + 1:
            continue

        best_return = 0.0
        best_match: ReturnMatch | None = None

        for i in range(len(monthly) - window_months):
            start_price = float(monthly.iloc[i])
            end_price = float(monthly.iloc[i + window_months])

            if start_price <= 0:
                continue

            ret = (end_price / start_price) - 1.0

            if ret >= return_threshold and ret > best_return:
                meta = ticker_metadata.get(ticker, {})
                best_return = ret
                best_match = ReturnMatch(
                    ticker=ticker,
                    name=meta.get("name", ticker),
                    country_iso2=meta.get("country_iso2", ""),
                    gics_code=meta.get("gics_code", ""),
                    window_start=monthly.index[i].date(),
                    window_end=monthly.index[i + window_months].date(),
                    start_price=round(start_price, 2),
                    end_price=round(end_price, 2),
                    return_pct=ret,
                )

        if best_match is not None:
            matches.append(best_match)
            log(
                f"  MATCH: {ticker} +{best_match.return_pct * 100:.0f}% "
                f"({best_match.window_start} to {best_match.window_end})"
            )

    matches.sort(key=lambda m: m.return_pct, reverse=True)
    return matches
