"""Score the universe from Parquet data using a trained ML model.

Standalone scoring pipeline — does NOT import from scorer.py or strategy.py.
Loads the same Parquet export used for training, takes each stock's most recent
fiscal year, predicts calibrated outperformance probabilities, and builds a
constrained portfolio with Kelly sizing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pyarrow.parquet as pq

from app.predict.model import TrainedModel
from app.predict.parquet_dataset import (
    _EXCLUDE_COLUMNS,
    _CATEGORICAL_COLUMNS,
)

# ── ML portfolio constants (relative outperformance model) ──────────────
ML_AVG_WIN = 0.42           # Average excess return for outperformers
ML_AVG_LOSS = -0.15         # Average excess return for underperformers
ML_KELLY_FRACTION = 0.25    # Quarter-Kelly
ML_MAX_POSITION = 0.10      # 10% max in any single stock
ML_MAX_COUNTRY = 0.30       # 30% max in any country
ML_MAX_SECTOR = 0.30        # 30% max in any sector
ML_MIN_PROBABILITY = 0.15   # 15% minimum to enter a position

# ── Confidence tiers ────────────────────────────────────────────────────
_CONFIDENCE_TIERS = [
    (0.30, "high"),
    (0.15, "medium"),
    (0.05, "low"),
    (0.0, "negligible"),
]


def _confidence_tier(probability: float) -> str:
    for threshold, tier in _CONFIDENCE_TIERS:
        if probability >= threshold:
            return tier
    return "negligible"


def _kelly_fraction(
    p_win: float,
    avg_win: float = ML_AVG_WIN,
    avg_loss: float = ML_AVG_LOSS,
    fraction: float = ML_KELLY_FRACTION,
) -> float:
    """Kelly criterion position size."""
    if p_win <= 0 or avg_win <= 0:
        return 0.0
    q = 1 - p_win
    f = p_win / abs(avg_loss) - q / avg_win
    return max(0.0, f * fraction)


@dataclass
class ScoredStock:
    """A stock scored by the ML model with portfolio weight."""

    ticker: str
    company_name: str
    country: str
    sector: str
    fiscal_year: int
    probability: float
    confidence: str
    kelly: float
    suggested_weight: float
    contributing_features: dict
    feature_values: dict


def score_from_parquet(
    parquet_path: str,
    model: TrainedModel,
    model_config: dict,
    log_fn: Callable[[str], None] | None = None,
    deduplicate: bool = True,
) -> list[ScoredStock]:
    """Score all stocks from the Parquet export.

    Loads the same Parquet file used for training, applies the same
    investability filters, takes each stock's most recent fiscal year,
    and produces calibrated probability scores.

    Args:
        parquet_path: Path to training_features.parquet.
        model: Trained model deserialized from DB.
        model_config: The model's train_config dict (contains filter params).
        log_fn: Optional logging callback.

    Returns:
        List of ScoredStock sorted by probability descending.
    """
    log = log_fn or (lambda _: None)

    # ── Load Parquet ────────────────────────────────────────────────────
    table = pq.read_table(parquet_path)
    df = table.to_pandas()
    log(f"Loaded Parquet: {len(df)} rows, {len(df.columns)} columns")

    # ── Apply same investability filters as training ────────────────────
    # Extract filter params from model config
    params = model_config.get("params", {})
    allowed_countries = params.get("allowed_countries") or model_config.get("allowed_countries")
    min_dollar_volume = params.get("min_dollar_volume") or model_config.get("min_dollar_volume")

    if allowed_countries:
        if isinstance(allowed_countries, str):
            allowed_countries = [c.strip() for c in allowed_countries.split(",")]
        before = len(df)
        df = df[df["country_iso2"].isin(allowed_countries)].copy()
        log(f"After country filter: {len(df)} rows (dropped {before - len(df)})")

    if min_dollar_volume is not None:
        before = len(df)
        df = df[
            df["dollar_volume_30d"].notna()
            & (df["dollar_volume_30d"] >= float(min_dollar_volume))
        ].copy()
        log(f"After min dollar volume >= ${float(min_dollar_volume):,.0f}: "
            f"{len(df)} rows (dropped {before - len(df)})")

    # ── Keep most recent fiscal year per ticker ─────────────────────────
    df = df.sort_values("fiscal_year", ascending=False)
    df = df.drop_duplicates(subset="ticker", keep="first").copy()
    log(f"After dedup (most recent year per ticker): {len(df)} rows")

    if len(df) == 0:
        log("No stocks to score.")
        return []

    # ── Extract metadata ────────────────────────────────────────────────
    tickers = df["ticker"].tolist()
    company_names = df["company_name"].fillna("").tolist()
    countries = df["country_iso2"].fillna("").tolist()
    gics_codes_raw = df["gics_code"].fillna("").astype(str).tolist()
    fiscal_years = df["fiscal_year"].values.astype(np.int64)

    # ── Build feature matrix (same processing as load_parquet_dataset) ──
    # Encode categoricals
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

    built_feature_names = list(X_df.columns)

    # ── Align features with model's expected order ──────────────────────
    model_features = model.feature_names
    n = len(df)
    X = np.full((n, len(model_features)), np.nan, dtype=np.float64)

    feature_idx = {name: i for i, name in enumerate(built_feature_names)}
    matched = 0
    for j, mf in enumerate(model_features):
        if mf in feature_idx:
            col_idx = feature_idx[mf]
            X[:, j] = X_df.iloc[:, col_idx].values.astype(np.float64)
            matched += 1

    log(f"Feature alignment: {matched}/{len(model_features)} features matched")

    # Replace non-finite with NaN
    X = np.where(np.isfinite(X), X, np.nan)

    # ── Predict ─────────────────────────────────────────────────────────
    probabilities = model.predict_proba(X)

    # ── Build feature importance info per stock ─────────────────────────
    top_features_global = list(model.feature_importance.items())[:10]

    scored: list[ScoredStock] = []
    for i in range(n):
        prob = float(probabilities[i])
        kelly = _kelly_fraction(prob)

        # Top contributing features
        contrib: dict = {}
        for feat_name, importance in top_features_global:
            j = model_features.index(feat_name) if feat_name in model_features else -1
            if j >= 0 and not math.isnan(X[i, j]):
                contrib[feat_name] = {
                    "value": round(float(X[i, j]), 4),
                    "importance": round(importance, 4),
                }
            if len(contrib) >= 5:
                break

        # All non-NaN feature values
        fvals: dict = {}
        for j, feat in enumerate(model_features):
            if not math.isnan(X[i, j]):
                fvals[feat] = round(float(X[i, j]), 4)

        # Map GICS code to sector name
        sector = _gics_to_sector(gics_codes_raw[i])

        scored.append(ScoredStock(
            ticker=tickers[i],
            company_name=company_names[i],
            country=countries[i],
            sector=sector,
            fiscal_year=int(fiscal_years[i]),
            probability=round(prob, 4),
            confidence=_confidence_tier(prob),
            kelly=round(kelly, 4),
            suggested_weight=0.0,  # Set by portfolio builder below
            contributing_features=contrib,
            feature_values=fvals,
        ))

    # Sort by probability descending
    scored.sort(key=lambda s: -s.probability)

    # ── Deduplicate by company name ───────────────────────────────────
    if deduplicate:
        seen: set[str] = set()
        deduped: list[ScoredStock] = []
        for s in scored:
            key = s.company_name.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        n_dupes = len(scored) - len(deduped)
        if n_dupes > 0:
            log(f"Deduplicated: removed {n_dupes} duplicate listings, "
                f"{len(deduped)} unique companies remain")
        scored = deduped

    # ── Portfolio construction ──────────────────────────────────────────
    _build_portfolio(scored, log)

    n_portfolio = sum(1 for s in scored if s.suggested_weight > 0)
    log(f"Scored {len(scored)} stocks, {n_portfolio} in portfolio")
    if scored:
        log(f"Top pick: {scored[0].ticker} ({scored[0].country}) "
            f"p={scored[0].probability:.1%}")

    return scored


def _build_portfolio(
    scored: list[ScoredStock],
    log: Callable[[str], None],
) -> None:
    """Apply Kelly sizing with position, country, and sector constraints.

    Modifies scored[].suggested_weight in place.
    """
    # Filter eligible
    eligible = [s for s in scored if s.probability >= ML_MIN_PROBABILITY and s.kelly > 0]

    # Cap individual positions
    for s in eligible:
        s.suggested_weight = min(s.kelly, ML_MAX_POSITION)

    # Apply country constraints
    country_weights: dict[str, float] = {}
    for s in eligible:
        current = country_weights.get(s.country, 0.0)
        remaining = ML_MAX_COUNTRY - current
        if remaining <= 0:
            s.suggested_weight = 0.0
        elif s.suggested_weight > remaining:
            s.suggested_weight = remaining
        country_weights[s.country] = country_weights.get(s.country, 0.0) + s.suggested_weight

    # Apply sector constraints
    sector_weights: dict[str, float] = {}
    for s in eligible:
        if s.suggested_weight <= 0:
            continue
        current = sector_weights.get(s.sector, 0.0)
        remaining = ML_MAX_SECTOR - current
        if remaining <= 0:
            s.suggested_weight = 0.0
        elif s.suggested_weight > remaining:
            s.suggested_weight = remaining
        sector_weights[s.sector] = sector_weights.get(s.sector, 0.0) + s.suggested_weight

    # Remove zero-weight
    with_weight = [s for s in eligible if s.suggested_weight > 0]

    # Normalize if total > 1.0
    total = sum(s.suggested_weight for s in with_weight)
    if total > 1.0:
        for s in with_weight:
            s.suggested_weight = round(s.suggested_weight / total, 4)

    # Log country breakdown
    country_summary: dict[str, float] = {}
    for s in with_weight:
        country_summary[s.country] = country_summary.get(s.country, 0.0) + s.suggested_weight
    if country_summary:
        parts = sorted(country_summary.items(), key=lambda x: -x[1])
        log("Country allocation: " + ", ".join(
            f"{c} {w:.1%}" for c, w in parts[:8]
        ))


# ── GICS sector mapping ────────────────────────────────────────────────

_GICS_SECTORS = {
    "10": "Energy",
    "15": "Materials",
    "20": "Industrials",
    "25": "Consumer Discretionary",
    "30": "Consumer Staples",
    "35": "Health Care",
    "40": "Financials",
    "45": "Information Technology",
    "50": "Communication Services",
    "55": "Utilities",
    "60": "Real Estate",
}


def _gics_to_sector(gics_code: str) -> str:
    """Map GICS code to sector name (first 2 digits)."""
    if not gics_code or len(gics_code) < 2:
        return "Unknown"
    return _GICS_SECTORS.get(gics_code[:2], "Unknown")
