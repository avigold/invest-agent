"""Compute deterministic scores from ML feature values.

Pure function — no DB access, no API calls. Takes a feature_values dict
(from PredictionScore.feature_values) and produces fundamental/market/company
scores plus a Buy/Hold/Sell classification using the same thresholds as the
legacy deterministic system.
"""
from __future__ import annotations

from app.score.absolute import absolute_score
from app.score.versions import (
    COMPANY_WEIGHTS,
    COMPANY_WEIGHTS_NO_FUNDAMENTALS,
    FUNDAMENTAL_ABSOLUTE_THRESHOLDS,
    MARKET_ABSOLUTE_THRESHOLDS,
    RECOMMENDATION_THRESHOLDS,
)

# Parquet feature name → deterministic market metric name
_MARKET_FEATURE_MAP = {
    "momentum_12m": "return_1y",
    "max_dd_12m": "max_drawdown",
    "ma_spread_20": "ma_spread",
}


def score_from_features(feature_values: dict) -> dict:
    """Compute deterministic scores from a feature_values dict.

    Returns a dict with fundamental_score, market_score, company_score,
    classification, and the individual ratios/metrics used.
    """
    # ── Fundamental ratios ──────────────────────────────────────────
    fundamental_ratios: dict[str, float | None] = {}
    fundamental_scores: list[float] = []

    for name, thresholds in FUNDAMENTAL_ABSOLUTE_THRESHOLDS.items():
        val = feature_values.get(name)
        if val is not None:
            # Ensure numeric (feature_values may have been serialised as int/float)
            val = float(val)
        fundamental_ratios[name] = val
        fundamental_scores.append(
            absolute_score(val, thresholds["floor"], thresholds["ceiling"],
                           thresholds["higher_is_better"])
        )

    has_fundamentals = any(v is not None for v in fundamental_ratios.values())
    fundamental_score = (
        sum(fundamental_scores) / len(fundamental_scores)
        if fundamental_scores else 50.0
    )

    # ── Market metrics ──────────────────────────────────────────────
    market_metrics: dict[str, float | None] = {}
    market_scores: list[float] = []

    for parquet_name, metric_name in _MARKET_FEATURE_MAP.items():
        val = feature_values.get(parquet_name)
        if val is not None:
            val = float(val)
        market_metrics[metric_name] = val
        thresholds = MARKET_ABSOLUTE_THRESHOLDS[metric_name]
        market_scores.append(
            absolute_score(val, thresholds["floor"], thresholds["ceiling"],
                           thresholds["higher_is_better"])
        )

    market_score = (
        sum(market_scores) / len(market_scores)
        if market_scores else 50.0
    )

    # ── Company score ───────────────────────────────────────────────
    weights = COMPANY_WEIGHTS if has_fundamentals else COMPANY_WEIGHTS_NO_FUNDAMENTALS
    company_score = round(
        weights["fundamental"] * fundamental_score
        + weights["market"] * market_score,
        2,
    )

    # ── Classification ──────────────────────────────────────────────
    if company_score > RECOMMENDATION_THRESHOLDS["buy"]:
        classification = "Buy"
    elif company_score < RECOMMENDATION_THRESHOLDS["sell"]:
        classification = "Sell"
    else:
        classification = "Hold"

    return {
        "fundamental_score": round(fundamental_score, 2),
        "market_score": round(market_score, 2),
        "company_score": company_score,
        "classification": classification,
        "fundamental_ratios": fundamental_ratios,
        "market_metrics": market_metrics,
    }
