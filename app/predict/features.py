"""Point-in-time feature computation for prediction model.

All features are computed using only data available at the observation date.
Monthly price series is the primary input — fundamentals are sparse and optional.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


# Feature names in canonical order (must match model training)
PRICE_FEATURES = [
    "momentum_3m",
    "momentum_6m",
    "momentum_12m",
    "momentum_24m",
    "momentum_accel",
    "relative_strength_12m",
    "volatility_6m",
    "volatility_12m",
    "vol_trend",
    "max_dd_12m",
    "max_dd_24m",
    "ma_spread_10",
    "ma_spread_20",
    "price_range_12m",
    "up_months_ratio_12m",
]

CROSS_SECTIONAL_FEATURES = [
    "momentum_12m_rank",
    "volatility_12m_rank",
]

FUNDAMENTAL_FEATURES = [
    "roe",
    "net_margin",
    "debt_equity",
    "revenue_growth",
    "fcf_yield",
]

ALL_FEATURES = PRICE_FEATURES + CROSS_SECTIONAL_FEATURES + FUNDAMENTAL_FEATURES


def _momentum(monthly: pd.Series, months: int) -> float | None:
    """Trailing return over `months` months."""
    if len(monthly) < months + 1:
        return None
    start = float(monthly.iloc[-(months + 1)])
    end = float(monthly.iloc[-1])
    if start <= 0:
        return None
    return (end / start) - 1.0


def _volatility(monthly: pd.Series, months: int) -> float | None:
    """Annualized volatility of monthly returns over trailing `months`."""
    if len(monthly) < months + 1:
        return None
    returns = monthly.pct_change().iloc[-months:]
    valid = returns.dropna()
    if len(valid) < 3:
        return None
    return float(valid.std() * math.sqrt(12))


def _max_drawdown(monthly: pd.Series, months: int) -> float | None:
    """Max peak-to-trough drawdown in trailing `months` months."""
    if len(monthly) < months + 1:
        return None
    segment = monthly.iloc[-(months + 1):]
    peak = segment.iloc[0]
    max_dd = 0.0
    for price in segment:
        if price > peak:
            peak = price
        if peak > 0:
            dd = (price - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return max_dd


def _ma_spread(monthly: pd.Series, periods: int) -> float | None:
    """Spread between current price and simple moving average."""
    if len(monthly) < periods:
        return None
    ma = float(monthly.iloc[-periods:].mean())
    if ma <= 0:
        return None
    return (float(monthly.iloc[-1]) - ma) / ma


def _price_range(monthly: pd.Series, months: int) -> float | None:
    """(high - low) / low over trailing `months` months."""
    if len(monthly) < months + 1:
        return None
    segment = monthly.iloc[-(months + 1):]
    lo = float(segment.min())
    hi = float(segment.max())
    if lo <= 0:
        return None
    return (hi - lo) / lo


def _up_months_ratio(monthly: pd.Series, months: int) -> float | None:
    """Fraction of positive monthly returns in trailing `months`."""
    if len(monthly) < months + 1:
        return None
    returns = monthly.pct_change().iloc[-months:]
    valid = returns.dropna()
    if len(valid) == 0:
        return None
    return float((valid > 0).sum() / len(valid))


def compute_price_features(
    monthly_prices: pd.Series,
    index_monthly: pd.Series | None = None,
) -> dict[str, float | None]:
    """Compute all price-derived features from a monthly price series.

    The series should end at the observation date — only trailing data.

    Args:
        monthly_prices: Monthly close prices for the stock, ending at obs_date.
        index_monthly: Optional monthly close prices for the country index,
            aligned to the same dates. Used for relative_strength_12m.

    Returns:
        Dict mapping feature names to values (None if insufficient data).
    """
    mom_6m = _momentum(monthly_prices, 6)
    mom_12m = _momentum(monthly_prices, 12)
    vol_6m = _volatility(monthly_prices, 6)
    vol_12m = _volatility(monthly_prices, 12)

    # Momentum acceleration: need 12m of data to compute a lagged 6m momentum
    momentum_accel = None
    if len(monthly_prices) >= 13:
        # 6m momentum as of 6 months ago
        lagged = monthly_prices.iloc[:-6]
        mom_6m_prior = _momentum(lagged, 6) if len(lagged) >= 7 else None
        if mom_6m is not None and mom_6m_prior is not None:
            momentum_accel = mom_6m - mom_6m_prior

    # Relative strength vs index
    relative_strength = None
    if index_monthly is not None and mom_12m is not None:
        idx_mom = _momentum(index_monthly, 12)
        if idx_mom is not None:
            relative_strength = mom_12m - idx_mom

    # Vol trend
    vol_trend = None
    if vol_6m is not None and vol_12m is not None and vol_12m > 0:
        vol_trend = vol_6m / vol_12m

    return {
        "momentum_3m": _momentum(monthly_prices, 3),
        "momentum_6m": mom_6m,
        "momentum_12m": mom_12m,
        "momentum_24m": _momentum(monthly_prices, 24),
        "momentum_accel": momentum_accel,
        "relative_strength_12m": relative_strength,
        "volatility_6m": vol_6m,
        "volatility_12m": vol_12m,
        "vol_trend": vol_trend,
        "max_dd_12m": _max_drawdown(monthly_prices, 12),
        "max_dd_24m": _max_drawdown(monthly_prices, 24),
        "ma_spread_10": _ma_spread(monthly_prices, 10),
        "ma_spread_20": _ma_spread(monthly_prices, 20),
        "price_range_12m": _price_range(monthly_prices, 12),
        "up_months_ratio_12m": _up_months_ratio(monthly_prices, 12),
    }


def compute_fundamental_features(
    fundamentals: dict[str, float | None],
) -> dict[str, float | None]:
    """Extract fundamental features from an observation's fundamentals dict.

    Args:
        fundamentals: Dict of fundamental values (may contain None).

    Returns:
        Dict mapping fundamental feature names to values.
    """
    return {
        "roe": fundamentals.get("roe"),
        "net_margin": fundamentals.get("net_margin"),
        "debt_equity": fundamentals.get("debt_equity"),
        "revenue_growth": fundamentals.get("revenue_growth"),
        "fcf_yield": fundamentals.get("fcf_yield"),
    }


def add_cross_sectional_ranks(
    feature_rows: list[dict[str, float | None]],
) -> None:
    """Add cross-sectional rank features in-place.

    Computes percentile ranks within the cohort for momentum_12m and
    volatility_12m. Only observations at the same date should be in
    the same cohort — caller is responsible for grouping.

    Args:
        feature_rows: List of feature dicts (one per observation).
            Modified in-place to add rank features.
    """
    for col in ("momentum_12m", "volatility_12m"):
        rank_col = f"{col}_rank"
        values = []
        indices = []
        for i, row in enumerate(feature_rows):
            v = row.get(col)
            if v is not None:
                values.append(v)
                indices.append(i)

        if not values:
            for row in feature_rows:
                row[rank_col] = None
            continue

        arr = np.array(values)
        # Compute percentile ranks (0 to 1)
        n = len(arr)
        order = arr.argsort().argsort()  # rank positions
        ranks = (order + 0.5) / n  # midpoint percentile ranks

        rank_map = {indices[j]: float(ranks[j]) for j in range(n)}
        for i, row in enumerate(feature_rows):
            row[rank_col] = rank_map.get(i)
