"""Load training data from Parquet export for LightGBM model training.

Reads the comprehensive training features Parquet file (PRD 7.4 output),
classifies columns, encodes categoricals, computes recency weights,
and produces a ParquetDataset ready for walk-forward training.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pyarrow.parquet as pq

from app.predict.dataset import Dataset


# Columns that are identifiers / metadata (not features)
_IDENTIFIER_COLUMNS = {
    "ticker", "company_name", "country_iso2", "gics_code",
    "fiscal_year", "statement_date", "reported_currency",
}

# Columns that are targets / labels (not features)
_TARGET_COLUMNS = {
    "fwd_return_3m", "fwd_return_6m", "fwd_return_12m", "fwd_return_24m",
    "fwd_max_dd_12m", "fwd_label",
}

# Columns that are always null in the export
_NULL_COLUMNS = {"relative_strength_12m", "beta_vs_index"}

# All columns to exclude from the feature matrix
_EXCLUDE_COLUMNS = _IDENTIFIER_COLUMNS | _TARGET_COLUMNS | _NULL_COLUMNS

# Columns to encode as LightGBM categoricals
_CATEGORICAL_COLUMNS = ["cat_gics_code", "cat_country_iso2"]


@dataclass
class ParquetDataset(Dataset):
    """Extended dataset with recency weights and fiscal year tracking."""

    weights: np.ndarray = field(default_factory=lambda: np.empty(0))
    fiscal_years: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    categorical_features: list[str] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    forward_returns: np.ndarray = field(default_factory=lambda: np.empty(0))
    half_life: float = 7.0


def compute_recency_weights(
    fiscal_years: np.ndarray,
    max_train_year: int,
    half_life: float = 7.0,
) -> np.ndarray:
    """Compute exponential decay sample weights.

    Args:
        fiscal_years: Array of fiscal years for each sample.
        max_train_year: The latest year in the training set.
        half_life: Number of years for weight to halve.

    Returns:
        Array of weights, each in (0, 1].
    """
    age = np.clip(max_train_year - fiscal_years, 0, None).astype(np.float64)
    return np.power(0.5, age / half_life)


def load_parquet_dataset(
    parquet_path: str,
    min_fiscal_year: int = 2000,
    half_life: float = 7.0,
    log_fn: Callable[[str], None] | None = None,
) -> ParquetDataset:
    """Load Parquet training data into a ParquetDataset.

    Args:
        parquet_path: Path to training_features.parquet.
        min_fiscal_year: Earliest fiscal year to include.
        half_life: Recency weighting half-life in years.
        log_fn: Optional logging callback.

    Returns:
        ParquetDataset ready for walk-forward training.
    """
    log = log_fn or (lambda _: None)

    # Read Parquet
    table = pq.read_table(parquet_path)
    df = table.to_pandas()
    log(f"Loaded Parquet: {len(df)} rows, {len(df.columns)} columns")

    # Filter by fiscal year
    df = df[df["fiscal_year"] >= min_fiscal_year].copy()
    log(f"After fiscal_year >= {min_fiscal_year}: {len(df)} rows")

    # Filter out rows without forward labels
    df = df[df["fwd_label"].notna()].copy()
    log(f"After dropping null fwd_label: {len(df)} rows")

    # Extract metadata before dropping columns
    tickers = df["ticker"].tolist()
    fiscal_years = df["fiscal_year"].values.astype(np.int64)
    fwd_returns = df["fwd_return_12m"].values.astype(np.float64)
    labels_str = df["fwd_label"].values

    # Build labels: winner=1, normal=0
    y = np.where(labels_str == "winner", 1.0, 0.0)

    # Encode categoricals before dropping identifier columns
    gics_codes = df["gics_code"].fillna("").astype(str)
    country_codes = df["country_iso2"].fillna("").astype(str)

    gics_categories = sorted(gics_codes.unique())
    country_categories = sorted(country_codes.unique())

    gics_map = {v: i for i, v in enumerate(gics_categories)}
    country_map = {v: i for i, v in enumerate(country_categories)}

    cat_gics = gics_codes.map(gics_map).values.astype(np.float64)
    cat_country = country_codes.map(country_map).values.astype(np.float64)

    # Drop non-feature columns
    feature_cols = [c for c in df.columns if c not in _EXCLUDE_COLUMNS]
    X_df = df[feature_cols].copy()

    # Add encoded categoricals
    X_df["cat_gics_code"] = cat_gics
    X_df["cat_country_iso2"] = cat_country

    feature_names = list(X_df.columns)
    X = X_df.values.astype(np.float64)

    # Replace pandas NaN with numpy NaN (should already be, but ensure)
    X = np.where(np.isfinite(X), X, np.nan)

    # Compute initial recency weights (based on max year in full dataset)
    max_year = int(fiscal_years.max())
    weights = compute_recency_weights(fiscal_years, max_year, half_life)

    n_winners = int(y.sum())
    log(
        f"Dataset ready: {len(y)} rows, {len(feature_names)} features, "
        f"{n_winners} winners ({n_winners / len(y):.1%}), "
        f"years {int(fiscal_years.min())}-{int(fiscal_years.max())}"
    )
    log(f"Categoricals: {len(gics_categories)} GICS codes, {len(country_categories)} countries")

    # Find indices of categorical features
    cat_feature_names = [c for c in feature_names if c in _CATEGORICAL_COLUMNS]

    return ParquetDataset(
        X=X,
        y=y,
        feature_names=feature_names,
        meta=[],  # Not used for Parquet pipeline
        weights=weights,
        fiscal_years=fiscal_years,
        categorical_features=cat_feature_names,
        tickers=tickers,
        forward_returns=fwd_returns,
        half_life=half_life,
    )
