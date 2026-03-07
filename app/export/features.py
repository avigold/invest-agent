"""Feature extraction from raw FMP artefact JSON for ML training.

Reads raw FMP financial statement JSON (all 140 fields) and computes:
- Raw financial fields (prefixed by statement type)
- ~40 derived ratios (profitability, leverage, efficiency, quality, growth)
- Piotroski F-Score
- Price-derived features (momentum, volatility, volume)
- Forward return labels
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from app.predict.features import compute_price_features


# ── Field definitions ────────────────────────────────────────────────

# Numeric fields to extract from each FMP statement type.
# Non-numeric metadata (date, symbol, cik, etc.) is excluded.

INCOME_NUMERIC_FIELDS = [
    "revenue", "costOfRevenue", "grossProfit",
    "researchAndDevelopmentExpenses", "generalAndAdministrativeExpenses",
    "sellingAndMarketingExpenses", "sellingGeneralAndAdministrativeExpenses",
    "otherExpenses", "operatingExpenses", "costAndExpenses",
    "netInterestIncome", "interestIncome", "interestExpense",
    "depreciationAndAmortization", "ebitda", "ebit",
    "nonOperatingIncomeExcludingInterest", "operatingIncome",
    "totalOtherIncomeExpensesNet", "incomeBeforeTax", "incomeTaxExpense",
    "netIncomeFromContinuingOperations", "netIncomeFromDiscontinuedOperations",
    "otherAdjustmentsToNetIncome", "netIncome", "netIncomeDeductions",
    "bottomLineNetIncome", "eps", "epsDiluted",
    "weightedAverageShsOut", "weightedAverageShsOutDil",
]

BALANCE_NUMERIC_FIELDS = [
    "cashAndCashEquivalents", "shortTermInvestments",
    "cashAndShortTermInvestments", "netReceivables", "accountsReceivables",
    "otherReceivables", "inventory", "prepaids", "otherCurrentAssets",
    "totalCurrentAssets", "propertyPlantEquipmentNet", "goodwill",
    "intangibleAssets", "goodwillAndIntangibleAssets", "longTermInvestments",
    "taxAssets", "otherNonCurrentAssets", "totalNonCurrentAssets",
    "otherAssets", "totalAssets", "totalPayables", "accountPayables",
    "otherPayables", "accruedExpenses", "shortTermDebt",
    "capitalLeaseObligationsCurrent", "taxPayables", "deferredRevenue",
    "otherCurrentLiabilities", "totalCurrentLiabilities", "longTermDebt",
    "capitalLeaseObligationsNonCurrent", "deferredRevenueNonCurrent",
    "deferredTaxLiabilitiesNonCurrent", "otherNonCurrentLiabilities",
    "totalNonCurrentLiabilities", "otherLiabilities",
    "capitalLeaseObligations", "totalLiabilities", "treasuryStock",
    "preferredStock", "commonStock", "retainedEarnings",
    "additionalPaidInCapital", "accumulatedOtherComprehensiveIncomeLoss",
    "otherTotalStockholdersEquity", "totalStockholdersEquity", "totalEquity",
    "minorityInterest", "totalLiabilitiesAndTotalEquity",
    "totalInvestments", "totalDebt", "netDebt",
]

CASHFLOW_NUMERIC_FIELDS = [
    "netIncome", "depreciationAndAmortization", "deferredIncomeTax",
    "stockBasedCompensation", "changeInWorkingCapital",
    "accountsReceivables", "inventory", "accountsPayables",
    "otherWorkingCapital", "otherNonCashItems",
    "netCashProvidedByOperatingActivities",
    "investmentsInPropertyPlantAndEquipment", "acquisitionsNet",
    "purchasesOfInvestments", "salesMaturitiesOfInvestments",
    "otherInvestingActivities", "netCashProvidedByInvestingActivities",
    "netDebtIssuance", "longTermNetDebtIssuance", "shortTermNetDebtIssuance",
    "netStockIssuance", "netCommonStockIssuance", "commonStockIssuance",
    "commonStockRepurchased", "netPreferredStockIssuance",
    "netDividendsPaid", "commonDividendsPaid", "preferredDividendsPaid",
    "otherFinancingActivities", "netCashProvidedByFinancingActivities",
    "effectOfForexChangesOnCash", "netChangeInCash",
    "cashAtEndOfPeriod", "cashAtBeginningOfPeriod",
    "operatingCashFlow", "capitalExpenditure", "freeCashFlow",
    "incomeTaxesPaid", "interestPaid",
]

_META_FIELDS = {"date", "symbol", "reportedCurrency", "cik", "filingDate",
                "acceptedDate", "fiscalYear", "calendarYear", "period"}

# All price-derived + forward return columns that must exist in every row.
# PyArrow infers schema from the first dict, so if early rows lack these
# keys, the columns get dropped from the entire output.
_ALL_PRICE_COLUMNS = [
    "momentum_3m", "momentum_6m", "momentum_12m", "momentum_24m",
    "momentum_accel", "relative_strength_12m",
    "volatility_3m", "volatility_6m", "volatility_12m", "vol_trend",
    "max_dd_12m", "max_dd_24m",
    "ma_spread_10", "ma_spread_20",
    "price_range_12m", "up_months_ratio_12m",
    "distance_from_52w_high", "distance_from_52w_low",
    "avg_daily_volume_30d", "avg_daily_volume_90d",
    "volume_trend", "dollar_volume_30d",
    "beta_vs_index",
    "fwd_return_3m", "fwd_return_6m", "fwd_return_12m", "fwd_return_24m",
    "fwd_max_dd_12m", "fwd_label",
]


# ── Helpers ──────────────────────────────────────────────────────────

def _safe_float(val) -> float | None:
    """Convert to float, returning None for missing/invalid values."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Safe division returning None on missing or zero denominator."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    result = numerator / denominator
    return result if math.isfinite(result) else None


def _fiscal_year(row: dict) -> int | None:
    """Extract fiscal year from FMP row."""
    for key in ("fiscalYear", "calendarYear"):
        val = row.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                continue
    d = row.get("date", "")
    if len(d) >= 4:
        try:
            return int(d[:4])
        except ValueError:
            pass
    return None


def _get(row: dict | None, field: str) -> float | None:
    """Get a numeric field from a statement row."""
    if row is None:
        return None
    return _safe_float(row.get(field))


def _yoy_growth(current: float | None, prior: float | None) -> float | None:
    """Year-over-year growth rate."""
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


# ── Raw financial extraction ────────────────────────────────────────

def extract_raw_financials(
    income: dict | None,
    balance: dict | None,
    cashflow: dict | None,
) -> dict[str, float | None]:
    """Extract all numeric fields from FMP statements, prefixed by type."""
    result: dict[str, float | None] = {}

    if income:
        for field in INCOME_NUMERIC_FIELDS:
            result[f"inc_{field}"] = _safe_float(income.get(field))

    if balance:
        for field in BALANCE_NUMERIC_FIELDS:
            result[f"bal_{field}"] = _safe_float(balance.get(field))

    if cashflow:
        for field in CASHFLOW_NUMERIC_FIELDS:
            result[f"cf_{field}"] = _safe_float(cashflow.get(field))

    return result


# ── Derived ratios ──────────────────────────────────────────────────

def compute_derived_ratios(
    income: dict | None,
    balance: dict | None,
    cashflow: dict | None,
    prior_income: dict | None = None,
    prior_balance: dict | None = None,
) -> dict[str, float | None]:
    """Compute ~40 derived ratios from FMP statement data."""
    ratios: dict[str, float | None] = {}

    # Shortcuts
    revenue = _get(income, "revenue")
    gross_profit = _get(income, "grossProfit")
    operating_income = _get(income, "operatingIncome")
    net_income = _get(income, "netIncome")
    ebitda = _get(income, "ebitda")
    income_before_tax = _get(income, "incomeBeforeTax")
    income_tax = _get(income, "incomeTaxExpense")
    interest_expense = _get(income, "interestExpense")
    da = _get(income, "depreciationAndAmortization")
    rd = _get(income, "researchAndDevelopmentExpenses")

    total_assets = _get(balance, "totalAssets")
    total_liabilities = _get(balance, "totalLiabilities")
    equity = _get(balance, "totalStockholdersEquity")
    total_current_assets = _get(balance, "totalCurrentAssets")
    total_current_liabilities = _get(balance, "totalCurrentLiabilities")
    total_debt = _get(balance, "totalDebt")
    net_debt = _get(balance, "netDebt")
    cash = _get(balance, "cashAndCashEquivalents")
    inventory = _get(balance, "inventory")
    receivables = _get(balance, "netReceivables")
    long_term_debt = _get(balance, "longTermDebt")

    ocf = _get(cashflow, "operatingCashFlow")
    capex = _get(cashflow, "capitalExpenditure")
    fcf = _get(cashflow, "freeCashFlow")
    sbc = _get(cashflow, "stockBasedCompensation")
    buybacks = _get(cashflow, "commonStockRepurchased")
    dividends = _get(cashflow, "netDividendsPaid")

    # ── Profitability ──
    ratios["gross_margin"] = _safe_div(gross_profit, revenue)
    ratios["operating_margin"] = _safe_div(operating_income, revenue)
    ratios["net_margin"] = _safe_div(net_income, revenue)
    ratios["ebitda_margin"] = _safe_div(ebitda, revenue)
    ratios["roe"] = _safe_div(net_income, equity)
    ratios["roa"] = _safe_div(net_income, total_assets)

    # ROIC = NOPAT / invested_capital
    nopat = None
    if operating_income is not None and income_tax is not None and income_before_tax is not None and income_before_tax != 0:
        tax_rate = income_tax / income_before_tax
        nopat = operating_income * (1 - tax_rate)
    invested_capital = None
    if equity is not None and total_debt is not None and cash is not None:
        invested_capital = equity + total_debt - cash
    ratios["roic"] = _safe_div(nopat, invested_capital)

    ratios["effective_tax_rate"] = _safe_div(income_tax, income_before_tax)

    # ── Leverage ──
    ratios["debt_equity"] = _safe_div(total_liabilities, equity)
    ratios["debt_assets"] = _safe_div(total_debt, total_assets)
    ratios["net_debt_ebitda"] = _safe_div(net_debt, ebitda)
    ratios["current_ratio"] = _safe_div(total_current_assets, total_current_liabilities)

    # Interest coverage = EBIT / interest_expense
    ebit = _get(income, "ebit")
    ratios["interest_coverage"] = _safe_div(ebit, interest_expense)
    ratios["cash_ratio"] = _safe_div(cash, total_current_liabilities)

    # ── Efficiency ──
    ratios["asset_turnover"] = _safe_div(revenue, total_assets)
    ratios["receivables_turnover"] = _safe_div(revenue, receivables)
    ratios["inventory_turnover"] = None
    cost_of_revenue = _get(income, "costOfRevenue")
    if cost_of_revenue is not None and inventory is not None and inventory > 0:
        ratios["inventory_turnover"] = cost_of_revenue / inventory
    ratios["capex_to_revenue"] = None
    if capex is not None and revenue is not None and revenue != 0:
        ratios["capex_to_revenue"] = abs(capex) / revenue

    # ── Quality / Accruals ──
    ratios["accruals_ratio"] = None
    if net_income is not None and ocf is not None and total_assets is not None and total_assets != 0:
        ratios["accruals_ratio"] = (net_income - ocf) / total_assets
    ratios["sbc_to_revenue"] = _safe_div(sbc, revenue)
    ratios["fcf_to_net_income"] = _safe_div(fcf, net_income)
    ratios["cash_conversion"] = _safe_div(ocf, net_income)
    ratios["earnings_quality"] = _safe_div(ocf, net_income)
    ratios["rd_to_revenue"] = _safe_div(rd, revenue)

    # ── Capital Allocation ──
    # Buyback yield: -buybacks / (shares * eps) as market cap proxy
    ratios["buyback_yield"] = None
    shares = _get(income, "weightedAverageShsOutDil")
    eps_val = _get(income, "epsDiluted")
    if buybacks is not None and shares is not None and eps_val is not None and shares > 0 and eps_val != 0:
        mkt_cap_proxy = shares * eps_val * (1 / ratios["roe"]) if ratios["roe"] and ratios["roe"] != 0 else None
        if mkt_cap_proxy and mkt_cap_proxy > 0:
            ratios["buyback_yield"] = -buybacks / mkt_cap_proxy

    ratios["dividend_payout"] = None
    if dividends is not None and net_income is not None and net_income != 0:
        ratios["dividend_payout"] = abs(dividends) / abs(net_income)

    ratios["capex_to_depreciation"] = None
    if capex is not None and da is not None and da != 0:
        ratios["capex_to_depreciation"] = abs(capex) / da

    # ── Growth YoY ──
    ratios["revenue_growth"] = _yoy_growth(revenue, _get(prior_income, "revenue"))
    ratios["gross_profit_growth"] = _yoy_growth(gross_profit, _get(prior_income, "grossProfit"))
    ratios["operating_income_growth"] = _yoy_growth(operating_income, _get(prior_income, "operatingIncome"))
    ratios["net_income_growth"] = _yoy_growth(net_income, _get(prior_income, "netIncome"))
    ratios["eps_growth"] = _yoy_growth(_get(income, "epsDiluted"), _get(prior_income, "epsDiluted"))
    ratios["fcf_growth"] = _yoy_growth(fcf, _get(None, "freeCashFlow") if prior_income is None else None)

    # FCF growth needs prior cashflow — we only have prior_income/prior_balance.
    # We'll handle this in the caller by passing prior cashflow when available.

    # ── Growth Trend ──
    # These require 3 years of data; compute current - prior YoY growth
    ratios["revenue_growth_accel"] = None  # computed by caller with 3 years
    ratios["margin_expansion"] = None
    prior_operating_margin = _safe_div(_get(prior_income, "operatingIncome"), _get(prior_income, "revenue"))
    if ratios["operating_margin"] is not None and prior_operating_margin is not None:
        ratios["margin_expansion"] = ratios["operating_margin"] - prior_operating_margin

    ratios["roe_change"] = None
    prior_roe = _safe_div(_get(prior_income, "netIncome"), _get(prior_balance, "totalStockholdersEquity"))
    if ratios["roe"] is not None and prior_roe is not None:
        ratios["roe_change"] = ratios["roe"] - prior_roe

    return ratios


# ── Piotroski F-Score ───────────────────────────────────────────────

def compute_piotroski_f_score(
    income: dict | None,
    balance: dict | None,
    cashflow: dict | None,
    prior_income: dict | None,
    prior_balance: dict | None,
    prior_cashflow: dict | None,
) -> int | None:
    """Compute Piotroski F-Score (0-9) from financial statement data.

    Returns None if insufficient data.
    """
    if income is None or balance is None or cashflow is None:
        return None

    score = 0
    net_income = _get(income, "netIncome")
    total_assets = _get(balance, "totalAssets")
    ocf = _get(cashflow, "operatingCashFlow")
    revenue = _get(income, "revenue")
    gross_profit = _get(income, "grossProfit")
    total_current_assets = _get(balance, "totalCurrentAssets")
    total_current_liabilities = _get(balance, "totalCurrentLiabilities")
    long_term_debt = _get(balance, "longTermDebt")
    shares = _get(income, "weightedAverageShsOutDil")

    prior_total_assets = _get(prior_balance, "totalAssets")
    prior_long_term_debt = _get(prior_balance, "longTermDebt")
    prior_current_ratio = _safe_div(
        _get(prior_balance, "totalCurrentAssets"),
        _get(prior_balance, "totalCurrentLiabilities"),
    )
    prior_shares = _get(prior_income, "weightedAverageShsOutDil")
    prior_gross_margin = _safe_div(_get(prior_income, "grossProfit"), _get(prior_income, "revenue"))
    prior_asset_turnover = _safe_div(_get(prior_income, "revenue"), prior_total_assets)

    # 1. ROA > 0
    roa = _safe_div(net_income, total_assets)
    if roa is not None and roa > 0:
        score += 1

    # 2. Operating cash flow > 0
    if ocf is not None and ocf > 0:
        score += 1

    # 3. ROA improving (current > prior)
    prior_roa = _safe_div(_get(prior_income, "netIncome"), prior_total_assets)
    if roa is not None and prior_roa is not None and roa > prior_roa:
        score += 1

    # 4. Cash flow > net income (accruals)
    if ocf is not None and net_income is not None and ocf > net_income:
        score += 1

    # 5. Long-term debt decreasing
    if long_term_debt is not None and prior_long_term_debt is not None:
        if long_term_debt < prior_long_term_debt:
            score += 1

    # 6. Current ratio improving
    current_ratio = _safe_div(total_current_assets, total_current_liabilities)
    if current_ratio is not None and prior_current_ratio is not None:
        if current_ratio > prior_current_ratio:
            score += 1

    # 7. No dilution (shares not increased)
    if shares is not None and prior_shares is not None:
        if shares <= prior_shares:
            score += 1

    # 8. Gross margin improving
    gross_margin = _safe_div(gross_profit, revenue)
    if gross_margin is not None and prior_gross_margin is not None:
        if gross_margin > prior_gross_margin:
            score += 1

    # 9. Asset turnover improving
    asset_turnover = _safe_div(revenue, total_assets)
    if asset_turnover is not None and prior_asset_turnover is not None:
        if asset_turnover > prior_asset_turnover:
            score += 1

    return score


# ── Price-derived features ──────────────────────────────────────────

def compute_trailing_price_features(
    prices: list[dict],
    as_of_date: date,
    index_prices: list[dict] | None = None,
) -> dict[str, float | None]:
    """Compute price + volume features using data up to as_of_date.

    Reuses app/predict/features.compute_price_features() for momentum/vol/dd,
    and adds volume features.

    Args:
        prices: [{date, price, volume}, ...] sorted oldest-first.
        as_of_date: compute features using only data <= this date.
        index_prices: optional country index prices for relative strength.
    """
    as_of_str = str(as_of_date)

    # Filter prices up to as_of_date
    trailing = [p for p in prices if p["date"] <= as_of_str]
    if len(trailing) < 2:
        return {}

    # Build monthly price series for existing features
    daily_closes = pd.Series(
        [p["price"] for p in trailing],
        index=pd.DatetimeIndex([p["date"] for p in trailing]),
        dtype=float,
    )
    monthly = daily_closes.resample("ME").last().dropna()

    # Index monthly if available
    idx_monthly = None
    if index_prices:
        idx_trailing = [p for p in index_prices if p["date"] <= as_of_str]
        if len(idx_trailing) >= 2:
            idx_daily = pd.Series(
                [p.get("price") or p.get("close", 0) for p in idx_trailing],
                index=pd.DatetimeIndex([p["date"] for p in idx_trailing]),
                dtype=float,
            )
            idx_monthly = idx_daily.resample("ME").last().dropna()

    # Reuse existing price features (15 features)
    result = compute_price_features(monthly, index_monthly=idx_monthly)

    # ── Additional volatility ──
    if len(monthly) >= 4:
        returns_3m = monthly.pct_change().iloc[-3:]
        valid = returns_3m.dropna()
        if len(valid) >= 2:
            result["volatility_3m"] = float(valid.std() * math.sqrt(12))
        else:
            result["volatility_3m"] = None
    else:
        result["volatility_3m"] = None

    # ── 52-week high/low distance ──
    if len(trailing) >= 252:
        last_252 = trailing[-252:]
        high_52w = max(p["price"] for p in last_252)
        low_52w = min(p["price"] for p in last_252)
        current = trailing[-1]["price"]
        result["distance_from_52w_high"] = (current - high_52w) / high_52w if high_52w > 0 else None
        result["distance_from_52w_low"] = (current - low_52w) / low_52w if low_52w > 0 else None
    else:
        result["distance_from_52w_high"] = None
        result["distance_from_52w_low"] = None

    # ── Volume features ──
    volumes = [p.get("volume") for p in trailing if p.get("volume") is not None]
    prices_with_vol = [(p["price"], p.get("volume", 0)) for p in trailing if p.get("volume")]

    if len(volumes) >= 30:
        vol_30d = volumes[-30:]
        vol_90d = volumes[-min(90, len(volumes)):]
        result["avg_daily_volume_30d"] = sum(vol_30d) / len(vol_30d)
        result["avg_daily_volume_90d"] = sum(vol_90d) / len(vol_90d)
        result["volume_trend"] = _safe_div(result["avg_daily_volume_30d"], result["avg_daily_volume_90d"])

        # Dollar volume
        recent_prices = [p["price"] for p in trailing[-30:]]
        if recent_prices:
            avg_price = sum(recent_prices) / len(recent_prices)
            result["dollar_volume_30d"] = result["avg_daily_volume_30d"] * avg_price
        else:
            result["dollar_volume_30d"] = None
    else:
        result["avg_daily_volume_30d"] = None
        result["avg_daily_volume_90d"] = None
        result["volume_trend"] = None
        result["dollar_volume_30d"] = None

    # ── Beta vs index ──
    result["beta_vs_index"] = None
    if idx_monthly is not None and len(monthly) >= 13 and len(idx_monthly) >= 13:
        stock_returns = monthly.pct_change().dropna().iloc[-12:]
        idx_returns = idx_monthly.pct_change().dropna()
        # Align by date
        common = stock_returns.index.intersection(idx_returns.index)
        if len(common) >= 6:
            sr = stock_returns.loc[common]
            ir = idx_returns.loc[common]
            cov = float(sr.cov(ir))
            var_idx = float(ir.var())
            if var_idx > 0:
                result["beta_vs_index"] = cov / var_idx

    return result


# ── Forward returns ─────────────────────────────────────────────────

def compute_forward_returns(
    prices: list[dict],
    as_of_date: date,
) -> dict[str, float | None]:
    """Compute forward returns at multiple horizons from as_of_date.

    Args:
        prices: [{date, price, volume}, ...] sorted oldest-first (full history).
        as_of_date: the observation date.

    Returns dict with fwd_return_3m, fwd_return_6m, fwd_return_12m,
    fwd_return_24m, fwd_max_dd_12m, fwd_label.
    """
    as_of_str = str(as_of_date)

    # Find observation price (closest price on or after as_of_date)
    obs_price = None
    obs_idx = None
    for i, p in enumerate(prices):
        if p["date"] >= as_of_str:
            obs_price = p["price"]
            obs_idx = i
            break

    if obs_price is None or obs_price <= 0:
        return {
            "fwd_return_3m": None, "fwd_return_6m": None,
            "fwd_return_12m": None, "fwd_return_24m": None,
            "fwd_max_dd_12m": None, "fwd_label": None,
        }

    result: dict[str, float | None] = {}
    future = prices[obs_idx:]

    horizons = {"3m": 63, "6m": 126, "12m": 252, "24m": 504}
    for label, trading_days in horizons.items():
        if len(future) > trading_days:
            end_price = future[trading_days]["price"]
            if end_price > 0:
                result[f"fwd_return_{label}"] = (end_price / obs_price) - 1.0
            else:
                result[f"fwd_return_{label}"] = None
        else:
            result[f"fwd_return_{label}"] = None

    # Forward max drawdown (12m)
    result["fwd_max_dd_12m"] = None
    fwd_12m = future[:253] if len(future) >= 253 else future
    if len(fwd_12m) >= 2:
        peak = obs_price
        max_dd = 0.0
        for p in fwd_12m:
            price = p["price"]
            if price > peak:
                peak = price
            if peak > 0:
                dd = (price - peak) / peak
                if dd < max_dd:
                    max_dd = dd
        result["fwd_max_dd_12m"] = max_dd

    # Label: winner if 12m return >= 100%
    fwd_12m_ret = result.get("fwd_return_12m")
    if fwd_12m_ret is not None:
        result["fwd_label"] = "winner" if fwd_12m_ret >= 1.0 else "normal"
    else:
        result["fwd_label"] = None

    return result


# ── Main entry point ────────────────────────────────────────────────

def extract_all_features(
    income_rows: list[dict],
    balance_rows: list[dict],
    cashflow_rows: list[dict],
    prices: list[dict],
    index_prices: list[dict] | None = None,
    context: dict | None = None,
) -> list[dict]:
    """Extract all features for a company, one dict per fiscal year.

    Args:
        income_rows: FMP income statement array (newest first).
        balance_rows: FMP balance sheet array (newest first).
        cashflow_rows: FMP cash flow array (newest first).
        prices: [{date, price, volume}, ...] sorted oldest-first.
        index_prices: optional country index prices for relative strength.
        context: optional {country_score, industry_score, ...}.

    Returns list of dicts, one per fiscal year, with all features.
    """
    # Index statements by fiscal year
    income_by_year = {_fiscal_year(r): r for r in income_rows if _fiscal_year(r)}
    balance_by_year = {_fiscal_year(r): r for r in balance_rows if _fiscal_year(r)}
    cashflow_by_year = {_fiscal_year(r): r for r in cashflow_rows if _fiscal_year(r)}

    # Get all fiscal years present in any statement
    all_years = sorted(
        set(income_by_year) | set(balance_by_year) | set(cashflow_by_year),
        reverse=True,
    )

    rows: list[dict] = []
    for i, fy in enumerate(all_years):
        inc = income_by_year.get(fy)
        bal = balance_by_year.get(fy)
        cf = cashflow_by_year.get(fy)

        # Prior year data
        prior_fy = fy - 1
        prior_inc = income_by_year.get(prior_fy)
        prior_bal = balance_by_year.get(prior_fy)
        prior_cf = cashflow_by_year.get(prior_fy)

        # Statement date (for price feature alignment)
        stmt_date_str = None
        for src in (inc, bal, cf):
            if src and src.get("date"):
                stmt_date_str = src["date"]
                break
        if stmt_date_str is None:
            stmt_date_str = f"{fy}-12-31"

        row: dict = {
            "fiscal_year": fy,
            "statement_date": stmt_date_str,
            "reported_currency": (inc or bal or cf or {}).get("reportedCurrency"),
        }

        # Raw financials
        row.update(extract_raw_financials(inc, bal, cf))

        # Derived ratios
        ratios = compute_derived_ratios(inc, bal, cf, prior_inc, prior_bal)

        # Fix FCF growth (needs prior cashflow)
        prior_fcf = _get(prior_cf, "freeCashFlow")
        current_fcf = _get(cf, "freeCashFlow")
        ratios["fcf_growth"] = _yoy_growth(current_fcf, prior_fcf)

        # Revenue growth acceleration (needs 3 years)
        prior_prior_fy = fy - 2
        prior_prior_inc = income_by_year.get(prior_prior_fy)
        if prior_prior_inc and prior_inc and inc:
            current_rev_growth = _yoy_growth(_get(inc, "revenue"), _get(prior_inc, "revenue"))
            prior_rev_growth = _yoy_growth(_get(prior_inc, "revenue"), _get(prior_prior_inc, "revenue"))
            if current_rev_growth is not None and prior_rev_growth is not None:
                ratios["revenue_growth_accel"] = current_rev_growth - prior_rev_growth

        row.update(ratios)

        # Piotroski F-Score
        row["piotroski_f_score"] = compute_piotroski_f_score(
            inc, bal, cf, prior_inc, prior_bal, prior_cf,
        )

        # Price features at statement date
        try:
            as_of = date.fromisoformat(stmt_date_str[:10])
        except ValueError:
            as_of = date(fy, 12, 31)

        if prices:
            price_feats = compute_trailing_price_features(prices, as_of, index_prices)
            row.update(price_feats)
            fwd = compute_forward_returns(prices, as_of)
            row.update(fwd)

        # Ensure all price/forward columns exist (even if no price data).
        # PyArrow from_pylist infers schema from the first row, so missing
        # keys in early rows cause columns to be dropped entirely.
        for col in _ALL_PRICE_COLUMNS:
            row.setdefault(col, None)

        # Context features
        if context:
            for k, v in context.items():
                row[f"ctx_{k}"] = v

        rows.append(row)

    return rows
