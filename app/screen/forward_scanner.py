"""Fixed forward return scanner — generates observations at annual intervals.

Instead of cherry-picking the best window per ticker, this scanner evaluates
every company at every annual observation point and measures what happened
over the next N years. Each observation includes trailing price-derived features
that are available for the full lookback period.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd


@dataclass
class Observation:
    """A single company at a single point in time, with forward outcome."""

    ticker: str
    name: str
    country_iso2: str
    gics_code: str
    obs_date: date

    # Forward outcome (measured over next N years)
    forward_return: float       # (end_price / start_price) - 1
    forward_max_dd: float       # Worst peak-to-trough in forward window (negative)
    label: str                  # "winner" | "catastrophe" | "normal"

    # Trailing price features (always available from price data)
    momentum_12m: float | None = None
    momentum_6m: float | None = None
    volatility_12m: float | None = None
    max_dd_12m: float | None = None
    ma_spread: float | None = None

    obs_price: float = 0.0

    # Fundamentals (sparse — populated later for recent observations)
    fundamentals: dict[str, float | None] = field(default_factory=dict)
    fundamentals_gap_days: int | None = None

    def to_dict(self) -> dict:
        """Serialize for JSONB storage."""
        return {
            "ticker": self.ticker,
            "name": self.name,
            "country_iso2": self.country_iso2,
            "gics_code": self.gics_code,
            "obs_date": str(self.obs_date),
            "forward_return": round(self.forward_return, 4),
            "forward_max_dd": round(self.forward_max_dd, 4),
            "label": self.label,
            "momentum_12m": round(self.momentum_12m, 4) if self.momentum_12m is not None else None,
            "momentum_6m": round(self.momentum_6m, 4) if self.momentum_6m is not None else None,
            "volatility_12m": round(self.volatility_12m, 4) if self.volatility_12m is not None else None,
            "max_dd_12m": round(self.max_dd_12m, 4) if self.max_dd_12m is not None else None,
            "ma_spread": round(self.ma_spread, 4) if self.ma_spread is not None else None,
            "obs_price": round(self.obs_price, 2),
            "fundamentals": {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in self.fundamentals.items()
            },
            "fundamentals_gap_days": self.fundamentals_gap_days,
        }


# ---------------------------------------------------------------------------
# Trailing feature helpers
# ---------------------------------------------------------------------------


def _max_drawdown(monthly_prices: pd.Series) -> float:
    """Compute max peak-to-trough drawdown within a price series."""
    if len(monthly_prices) < 2:
        return 0.0
    peak = monthly_prices.iloc[0]
    max_dd = 0.0
    for price in monthly_prices:
        if price > peak:
            peak = price
        if peak > 0:
            dd = (price - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return max_dd


def _trailing_momentum(monthly: pd.Series, months: int) -> float | None:
    """Trailing return over `months` months."""
    if len(monthly) < months + 1:
        return None
    start = float(monthly.iloc[-(months + 1)])
    end = float(monthly.iloc[-1])
    if start <= 0:
        return None
    return (end / start) - 1.0


def _trailing_volatility(monthly: pd.Series, months: int) -> float | None:
    """Annualized volatility of monthly returns."""
    if len(monthly) < months + 1:
        return None
    returns = monthly.pct_change().iloc[-months:]
    if returns.isna().all():
        return None
    return float(returns.std() * math.sqrt(12))


def _trailing_max_drawdown(monthly: pd.Series, months: int) -> float | None:
    """Max drawdown in trailing `months` months."""
    if len(monthly) < months + 1:
        return None
    segment = monthly.iloc[-(months + 1):]
    return _max_drawdown(segment)


def _trailing_ma_spread(monthly: pd.Series, ma_periods: int = 10) -> float | None:
    """Spread between current price and simple moving average."""
    if len(monthly) < ma_periods:
        return None
    ma = float(monthly.iloc[-ma_periods:].mean())
    if ma <= 0:
        return None
    return (float(monthly.iloc[-1]) - ma) / ma


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------


def generate_observations(
    prices: dict[str, pd.Series],
    ticker_metadata: dict[str, dict],
    window_years: int,
    return_threshold: float,
    catastrophe_threshold: float = -0.80,
    observation_interval_months: int = 12,
    log_fn: Callable[[str], None] | None = None,
) -> list[Observation]:
    """Generate fixed-forward observations at annual intervals.

    For each ticker at each observation date, measures the forward N-year
    return and computes trailing price-derived features.

    Args:
        prices: {ticker: pd.Series of daily close prices}
        ticker_metadata: {ticker: {name, country_iso2, gics_code}}
        window_years: forward window size (e.g. 5)
        return_threshold: winner threshold (e.g. 3.0 for 300%)
        catastrophe_threshold: max drawdown to flag as catastrophe (e.g. -0.80)
        observation_interval_months: spacing between observations (default 12)

    Returns: list of Observation objects
    """
    log = log_fn or (lambda _: None)
    window_months = window_years * 12
    observations: list[Observation] = []

    for ticker, price_series in prices.items():
        monthly = price_series.resample("ME").last().dropna()

        if len(monthly) < window_months + 1:
            continue

        meta = ticker_metadata.get(ticker, {})

        # Step through at observation_interval_months intervals
        i = 0
        while i + window_months < len(monthly):
            obs_price = float(monthly.iloc[i])
            end_price = float(monthly.iloc[i + window_months])

            if obs_price <= 0:
                i += observation_interval_months
                continue

            forward_return = (end_price / obs_price) - 1.0
            forward_window = monthly.iloc[i: i + window_months + 1]
            forward_dd = _max_drawdown(forward_window)

            # Label
            is_winner = forward_return >= return_threshold
            is_catastrophe = forward_dd <= catastrophe_threshold
            if is_winner:
                label = "winner"
            elif is_catastrophe:
                label = "catastrophe"
            else:
                label = "normal"

            # Trailing features (using data up to and including obs_date)
            trailing_data = monthly.iloc[: i + 1]

            obs = Observation(
                ticker=ticker,
                name=meta.get("name", ticker),
                country_iso2=meta.get("country_iso2", ""),
                gics_code=meta.get("gics_code", ""),
                obs_date=monthly.index[i].date(),
                forward_return=forward_return,
                forward_max_dd=forward_dd,
                label=label,
                momentum_12m=_trailing_momentum(trailing_data, 12),
                momentum_6m=_trailing_momentum(trailing_data, 6),
                volatility_12m=_trailing_volatility(trailing_data, 12),
                max_dd_12m=_trailing_max_drawdown(trailing_data, 12),
                ma_spread=_trailing_ma_spread(trailing_data, 10),
                obs_price=obs_price,
            )
            observations.append(obs)

            i += observation_interval_months

    winners = sum(1 for o in observations if o.label == "winner")
    catastrophes = sum(1 for o in observations if o.label == "catastrophe")
    log(
        f"Generated {len(observations)} observations: "
        f"{winners} winners, {catastrophes} catastrophes, "
        f"{len(observations) - winners - catastrophes} normal"
    )

    return observations
