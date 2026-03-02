"""Fetch extended price histories from yfinance for screening."""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Callable

import pandas as pd


def _batch_download_prices(
    tickers: list[str],
    start: str,
    end: str,
) -> dict[str, pd.Series]:
    """Download daily close prices for multiple tickers via yfinance.

    Synchronous — caller wraps in run_in_executor.
    Returns {ticker: pd.Series of daily close prices}.
    """
    import yfinance as yf

    df = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )

    result: dict[str, pd.Series] = {}

    if df.empty:
        return result

    if len(tickers) == 1:
        ticker = tickers[0]
        if "Close" in df.columns:
            close = df["Close"].dropna()
            if not close.empty:
                result[ticker] = close
    else:
        for ticker in tickers:
            try:
                close = df[ticker]["Close"].dropna()
                if not close.empty:
                    result[ticker] = close
            except (KeyError, TypeError):
                continue

    return result


async def fetch_extended_prices(
    tickers: list[str],
    start_date: str,
    end_date: str,
    batch_size: int = 50,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, pd.Series]:
    """Fetch extended price histories in batches.

    Returns {ticker: pd.Series of daily close prices indexed by date}.
    """
    log = log_fn or (lambda _: None)
    loop = asyncio.get_running_loop()
    all_prices: dict[str, pd.Series] = {}

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(tickers) + batch_size - 1) // batch_size
        log(f"  Fetching prices batch {batch_num}/{total_batches}: {len(batch)} tickers")

        batch_result = await loop.run_in_executor(
            None,
            partial(_batch_download_prices, batch, start_date, end_date),
        )
        all_prices.update(batch_result)

    return all_prices
