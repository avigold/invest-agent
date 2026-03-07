"""Build feature matrix from observations for model training.

Takes observations from forward_scanner.py and computes the full feature set.
Returns numpy arrays ready for LightGBM training.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from app.predict.features import (
    ALL_FEATURES,
    add_cross_sectional_ranks,
    compute_fundamental_features,
    compute_price_features,
)
from app.screen.forward_scanner import Observation


@dataclass
class ObservationMeta:
    """Metadata for each row in the feature matrix."""

    ticker: str
    obs_date: date
    forward_return: float
    label: str


@dataclass
class Dataset:
    """Feature matrix with labels and metadata."""

    X: np.ndarray                  # (n_obs, n_features) — float, may contain NaN
    y: np.ndarray                  # (n_obs,) — binary labels (1=winner, 0=other)
    feature_names: list[str]
    meta: list[ObservationMeta]

    @property
    def n_observations(self) -> int:
        return len(self.y)

    @property
    def n_features(self) -> int:
        return len(self.feature_names)

    @property
    def n_winners(self) -> int:
        return int(self.y.sum())

    @property
    def base_rate(self) -> float:
        if self.n_observations == 0:
            return 0.0
        return self.n_winners / self.n_observations


def build_dataset(
    observations: list[Observation],
    prices: dict[str, pd.Series],
    index_prices: dict[str, pd.Series] | None = None,
) -> Dataset:
    """Build feature matrix from observations.

    For each observation, computes price-derived features from the monthly
    price series up to the observation date, fundamental features from
    the observation's stored fundamentals, and cross-sectional ranks
    within each observation-date cohort.

    Args:
        observations: List of Observation objects from forward_scanner.
        prices: {ticker: pd.Series} of daily close prices (full history).
        index_prices: Optional {country_iso2: pd.Series} for country indices.
            Used for relative_strength_12m.

    Returns:
        Dataset with feature matrix, labels, and metadata.
    """
    if not observations:
        return Dataset(
            X=np.empty((0, len(ALL_FEATURES))),
            y=np.empty(0),
            feature_names=list(ALL_FEATURES),
            meta=[],
        )

    # Resample prices to monthly once per ticker
    monthly_cache: dict[str, pd.Series] = {}
    for ticker, ps in prices.items():
        monthly_cache[ticker] = ps.resample("ME").last().dropna()

    # Resample index prices
    index_monthly_cache: dict[str, pd.Series] = {}
    if index_prices:
        for iso2, ps in index_prices.items():
            index_monthly_cache[iso2] = ps.resample("ME").last().dropna()

    # Group observations by obs_date for cross-sectional ranking
    by_date: dict[date, list[int]] = {}
    feature_rows: list[dict[str, float | None]] = []
    meta_list: list[ObservationMeta] = []
    labels: list[int] = []

    for i, obs in enumerate(observations):
        # Compute price features using trailing data up to obs_date
        monthly = monthly_cache.get(obs.ticker)
        if monthly is None or monthly.empty:
            # No price data — skip this observation
            continue

        # Slice to data up to and including obs_date
        obs_ts = pd.Timestamp(obs.obs_date)
        trailing = monthly[monthly.index <= obs_ts]
        if trailing.empty:
            continue

        # Get index for relative strength
        idx_monthly = None
        if obs.country_iso2 and obs.country_iso2 in index_monthly_cache:
            idx_full = index_monthly_cache[obs.country_iso2]
            idx_monthly = idx_full[idx_full.index <= obs_ts]
            if idx_monthly.empty:
                idx_monthly = None

        # Price features
        pf = compute_price_features(trailing, index_monthly=idx_monthly)

        # Fundamental features
        ff = compute_fundamental_features(obs.fundamentals or {})

        # Merge
        row = {**pf, **ff}
        feature_rows.append(row)

        meta_list.append(ObservationMeta(
            ticker=obs.ticker,
            obs_date=obs.obs_date,
            forward_return=obs.forward_return,
            label=obs.label,
        ))
        labels.append(1 if obs.label == "winner" else 0)

        # Track date group
        d = obs.obs_date
        by_date.setdefault(d, []).append(len(feature_rows) - 1)

    # Add cross-sectional ranks per date cohort
    for indices in by_date.values():
        cohort = [feature_rows[i] for i in indices]
        add_cross_sectional_ranks(cohort)
        # Write back (cohort items are the same dicts)

    # Build numpy arrays
    n = len(feature_rows)
    X = np.full((n, len(ALL_FEATURES)), np.nan)
    for i, row in enumerate(feature_rows):
        for j, feat in enumerate(ALL_FEATURES):
            v = row.get(feat)
            if v is not None:
                X[i, j] = v

    return Dataset(
        X=X,
        y=np.array(labels, dtype=np.float64),
        feature_names=list(ALL_FEATURES),
        meta=meta_list,
    )
