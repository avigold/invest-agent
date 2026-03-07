"""Fetch fundamental data near the start of each matched window."""
from __future__ import annotations

import asyncio
from datetime import date
from functools import partial
from typing import TYPE_CHECKING, Callable

import httpx
import pandas as pd

from app.config import get_settings

if TYPE_CHECKING:
    from app.screen.forward_scanner import Observation
    from app.screen.return_scanner import ReturnMatch


# ---------------------------------------------------------------------------
# yfinance path (legacy fallback)
# ---------------------------------------------------------------------------

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

    # Track how far the fiscal data is from the target date
    fiscal_gap_days = abs((chosen_date - target_ts).days)

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

    # Store metadata about the actual fiscal date used
    fundamentals["_fiscal_date"] = str(chosen_date.date())
    fundamentals["_fiscal_gap_days"] = fiscal_gap_days

    return fundamentals


# ---------------------------------------------------------------------------
# FMP path (primary — 13-41 years of history)
# ---------------------------------------------------------------------------

async def _fetch_fmp_financials(
    client: httpx.AsyncClient,
    ticker: str,
    api_key: str,
) -> dict[str, list[dict]]:
    """Fetch FMP financial statements for a ticker.

    Returns ``{"income": [...], "balance": [...], "cashflow": [...]}``.
    """
    from app.ingest.fmp import (
        fetch_balance_sheet,
        fetch_cash_flow,
        fetch_income_statement,
    )

    result: dict[str, list[dict]] = {}
    for key, fetch_fn in [
        ("income", fetch_income_statement),
        ("balance", fetch_balance_sheet),
        ("cashflow", fetch_cash_flow),
    ]:
        try:
            data, _raw = await fetch_fn(client, ticker, api_key, limit=50)
            result[key] = data
        except Exception:
            result[key] = []
    return result


def extract_fmp_fundamentals_near_date(
    financials: dict[str, list[dict]],
    target_date: date,
) -> dict[str, float | None]:
    """Extract key ratios from FMP data nearest to (but not after) target_date.

    Same output contract as ``extract_fundamentals_near_date()``.
    """
    income_rows = financials.get("income", [])
    balance_rows = financials.get("balance", [])
    cashflow_rows = financials.get("cashflow", [])

    def _find_nearest(rows: list[dict]) -> dict | None:
        best = None
        best_date: date | None = None
        for row in rows:
            d_str = row.get("date", "")
            if len(d_str) < 10:
                continue
            try:
                row_date = date.fromisoformat(d_str[:10])
            except ValueError:
                continue
            if row_date <= target_date:
                if best_date is None or row_date > best_date:
                    best = row
                    best_date = row_date
        return best

    income = _find_nearest(income_rows)
    balance = _find_nearest(balance_rows)
    cashflow = _find_nearest(cashflow_rows)

    if not income:
        return {}

    income_date = date.fromisoformat(income["date"][:10])
    fiscal_gap_days = abs((target_date - income_date).days)

    def _get(row: dict | None, key: str) -> float | None:
        if row is None:
            return None
        val = row.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    revenue = _get(income, "revenue")
    net_income = _get(income, "netIncome")
    total_equity = _get(balance, "totalStockholdersEquity")
    total_assets = _get(balance, "totalAssets")
    total_liabilities = _get(balance, "totalLiabilities")
    operating_cf = _get(cashflow, "operatingCashFlow")
    capex = _get(cashflow, "capitalExpenditure")

    fundamentals: dict[str, float | None] = {}
    fundamentals["revenue"] = revenue

    if revenue and net_income and revenue != 0:
        fundamentals["net_margin"] = round(net_income / revenue, 4)

    if total_equity and net_income and total_equity != 0:
        fundamentals["roe"] = round(net_income / total_equity, 4)

    if total_equity and total_liabilities and total_equity != 0:
        fundamentals["debt_equity"] = round(total_liabilities / total_equity, 4)

    if operating_cf is not None and capex is not None:
        # FMP capex is already positive
        fundamentals["fcf"] = operating_cf - capex

    if revenue and total_assets and total_assets != 0:
        fundamentals["asset_turnover"] = round(revenue / total_assets, 4)

    fundamentals["_fiscal_date"] = str(income_date)
    fundamentals["_fiscal_gap_days"] = fiscal_gap_days

    return fundamentals


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_fundamentals_for_matches(
    matches: list[ReturnMatch],
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, dict[str, float | None]]:
    """For each match, fetch fundamentals near the window start.

    Returns {ticker: {metric: value}}.
    """
    log = log_fn or (lambda _: None)
    settings = get_settings()
    result: dict[str, dict] = {}

    unique_tickers = list({m.ticker: m for m in matches}.values())
    log(f"Fetching fundamentals for {len(unique_tickers)} matched tickers...")

    if settings.fmp_api_key:
        async with httpx.AsyncClient() as client:
            for match in unique_tickers:
                try:
                    financials = await _fetch_fmp_financials(
                        client, match.ticker, settings.fmp_api_key,
                    )
                    fundamentals = extract_fmp_fundamentals_near_date(
                        financials, match.window_start,
                    )
                    if fundamentals:
                        result[match.ticker] = fundamentals
                        log(f"  {match.ticker}: {len(fundamentals)} metrics (FMP)")
                        continue
                except Exception:
                    pass
                # Fallback to yfinance
                try:
                    loop = asyncio.get_running_loop()
                    yf_data = await loop.run_in_executor(
                        None, partial(_fetch_ticker_financials, match.ticker),
                    )
                    fundamentals = extract_fundamentals_near_date(yf_data, match.window_start)
                    result[match.ticker] = fundamentals
                    log(f"  {match.ticker}: {len(fundamentals)} metrics (yfinance fallback)")
                except Exception as e:
                    log(f"  {match.ticker}: WARN failed to fetch fundamentals: {e}")
                    result[match.ticker] = {}
    else:
        loop = asyncio.get_running_loop()
        for match in unique_tickers:
            try:
                financials = await loop.run_in_executor(
                    None, partial(_fetch_ticker_financials, match.ticker),
                )
                fundamentals = extract_fundamentals_near_date(financials, match.window_start)
                result[match.ticker] = fundamentals
                log(f"  {match.ticker}: {len(fundamentals)} metrics extracted")
            except Exception as e:
                log(f"  {match.ticker}: WARN failed to fetch fundamentals: {e}")
                result[match.ticker] = {}

    return result


async def fetch_fundamentals_for_observations(
    observations: list[Observation],
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """Attach fundamentals to observations in-place.

    Uses FMP if configured (13-41 years of history), otherwise falls back
    to yfinance (~4 years). Observations where the fiscal gap exceeds
    3 years are left with empty fundamentals.
    """
    log = log_fn or (lambda _: None)
    settings = get_settings()

    MAX_GAP_DAYS = 365 * 3

    # Group observations by ticker
    by_ticker: dict[str, list[Observation]] = {}
    for obs in observations:
        by_ticker.setdefault(obs.ticker, []).append(obs)

    log(f"Fetching fundamentals for {len(by_ticker)} tickers "
        f"({len(observations)} observations)...")

    if settings.fmp_api_key:
        await _fetch_observations_fmp(by_ticker, settings.fmp_api_key, MAX_GAP_DAYS, log)
    else:
        await _fetch_observations_yfinance(by_ticker, MAX_GAP_DAYS, log)


async def _fetch_observations_fmp(
    by_ticker: dict[str, list[Observation]],
    api_key: str,
    max_gap_days: int,
    log: Callable[[str], None],
) -> None:
    """Attach fundamentals using FMP, with per-ticker yfinance fallback."""
    async with httpx.AsyncClient() as client:
        for ticker, ticker_obs in by_ticker.items():
            fmp_ok = False
            try:
                financials = await _fetch_fmp_financials(client, ticker, api_key)
                # Check if FMP returned any data
                if any(financials.get(k) for k in ("income", "balance", "cashflow")):
                    fmp_ok = True
                    attached = 0
                    stale = 0
                    for obs in ticker_obs:
                        fdata = extract_fmp_fundamentals_near_date(financials, obs.obs_date)
                        gap = fdata.get("_fiscal_gap_days")
                        if gap is not None and gap > max_gap_days:
                            stale += 1
                            obs.fundamentals_gap_days = gap
                            continue
                        clean = {
                            k: v for k, v in fdata.items()
                            if not k.startswith("_") and v is not None
                        }
                        obs.fundamentals = clean
                        obs.fundamentals_gap_days = gap
                        if clean:
                            attached += 1
                    log(f"  {ticker}: {attached}/{len(ticker_obs)} observations "
                        f"with fundamentals, {stale} stale (FMP)")
            except Exception:
                pass

            if not fmp_ok:
                # Fallback to yfinance for this ticker
                await _fetch_ticker_yfinance(ticker, ticker_obs, max_gap_days, log)


async def _fetch_observations_yfinance(
    by_ticker: dict[str, list[Observation]],
    max_gap_days: int,
    log: Callable[[str], None],
) -> None:
    """Attach fundamentals using yfinance (legacy path)."""
    for ticker, ticker_obs in by_ticker.items():
        await _fetch_ticker_yfinance(ticker, ticker_obs, max_gap_days, log)


async def _fetch_ticker_yfinance(
    ticker: str,
    ticker_obs: list[Observation],
    max_gap_days: int,
    log: Callable[[str], None],
) -> None:
    """Fetch yfinance fundamentals for a single ticker's observations."""
    loop = asyncio.get_running_loop()
    try:
        financials = await loop.run_in_executor(
            None, partial(_fetch_ticker_financials, ticker),
        )
        attached = 0
        stale = 0
        for obs in ticker_obs:
            fdata = extract_fundamentals_near_date(financials, obs.obs_date)
            gap = fdata.get("_fiscal_gap_days")
            if gap is not None and gap > max_gap_days:
                stale += 1
                obs.fundamentals_gap_days = gap
                continue
            clean = {
                k: v for k, v in fdata.items()
                if not k.startswith("_") and v is not None
            }
            obs.fundamentals = clean
            obs.fundamentals_gap_days = gap
            if clean:
                attached += 1
        log(f"  {ticker}: {attached}/{len(ticker_obs)} observations "
            f"with fundamentals, {stale} stale (yfinance)")
    except Exception as e:
        log(f"  {ticker}: WARN failed to fetch fundamentals: {e}")
