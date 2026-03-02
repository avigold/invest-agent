"""Fetch fundamental data near the start of each matched window."""
from __future__ import annotations

import asyncio
from datetime import date
from functools import partial
from typing import TYPE_CHECKING, Callable

import pandas as pd

if TYPE_CHECKING:
    from app.screen.return_scanner import ReturnMatch


def _fetch_ticker_financials(ticker: str) -> dict[str, pd.DataFrame]:
    """Fetch financial statements from yfinance (sync)."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    result: dict[str, pd.DataFrame] = {}
    for attr in ("income_stmt", "balance_sheet", "cashflow"):
        df = getattr(t, attr, None)
        if df is not None and not df.empty:
            result[attr] = df
        else:
            result[attr] = pd.DataFrame()
    return result


def extract_fundamentals_near_date(
    financials: dict[str, pd.DataFrame],
    target_date: date,
) -> dict[str, float | None]:
    """Extract key ratios from the fiscal year closest to (but not after) target_date."""
    income = financials.get("income_stmt", pd.DataFrame())
    balance = financials.get("balance_sheet", pd.DataFrame())
    cashflow = financials.get("cashflow", pd.DataFrame())

    if income.empty:
        return {}

    # Find the column closest to (but not after) the target date
    target_ts = pd.Timestamp(target_date)
    available_dates = sorted(income.columns, reverse=True)
    chosen_date = None
    for d in available_dates:
        if d <= target_ts:
            chosen_date = d
            break
    if chosen_date is None and available_dates:
        chosen_date = available_dates[-1]

    if chosen_date is None:
        return {}

    def _get(df: pd.DataFrame, keys: list[str]) -> float | None:
        for key in keys:
            if key in df.index and chosen_date in df.columns:
                val = df.loc[key, chosen_date]
                if pd.notna(val):
                    return float(val)
        return None

    revenue = _get(income, ["Total Revenue", "Revenue"])
    net_income = _get(income, ["Net Income", "Net Income Common Stockholders"])
    total_equity = _get(
        balance, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"]
    )
    total_assets = _get(balance, ["Total Assets"])
    total_debt = _get(balance, ["Total Debt", "Long Term Debt"])
    operating_cf = _get(
        cashflow, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]
    )
    capex = _get(cashflow, ["Capital Expenditure", "Capital Expenditures"])

    fundamentals: dict[str, float | None] = {}
    fundamentals["revenue"] = revenue

    if revenue and net_income and revenue != 0:
        fundamentals["net_margin"] = round(net_income / revenue, 4)

    if total_equity and net_income and total_equity != 0:
        fundamentals["roe"] = round(net_income / total_equity, 4)

    if total_equity and total_debt and total_equity != 0:
        fundamentals["debt_equity"] = round(total_debt / total_equity, 4)

    if operating_cf is not None and capex is not None:
        fundamentals["fcf"] = operating_cf - abs(capex)

    if revenue and total_assets and total_assets != 0:
        fundamentals["asset_turnover"] = round(revenue / total_assets, 4)

    return fundamentals


async def fetch_fundamentals_for_matches(
    matches: list[ReturnMatch],
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, dict[str, float | None]]:
    """For each match, fetch fundamentals near the window start.

    Returns {ticker: {metric: value}}.
    """
    log = log_fn or (lambda _: None)
    loop = asyncio.get_running_loop()
    result: dict[str, dict] = {}

    unique_tickers = list({m.ticker: m for m in matches}.values())
    log(f"Fetching fundamentals for {len(unique_tickers)} matched tickers...")

    for match in unique_tickers:
        try:
            financials = await loop.run_in_executor(
                None,
                partial(_fetch_ticker_financials, match.ticker),
            )
            fundamentals = extract_fundamentals_near_date(financials, match.window_start)
            result[match.ticker] = fundamentals
            log(f"  {match.ticker}: {len(fundamentals)} metrics extracted")
        except Exception as e:
            log(f"  {match.ticker}: WARN failed to fetch fundamentals: {e}")
            result[match.ticker] = {}

    return result
