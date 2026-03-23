"""DETERMINISTIC SCORING SYSTEM — score current universe.

Part of the deterministic scoring system. Do not confuse with the ML/Parquet
system (parquet_scorer.py, parquet_dataset.py, model.py).

Loads companies from the database, computes current features (22 features),
and produces calibrated probability scores with confidence tiers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanyScore
from app.predict.features import (
    ALL_FEATURES,
    add_cross_sectional_ranks,
    compute_fundamental_features,
    compute_price_features,
)
from app.predict.model import TrainedModel
from app.predict.strategy import kelly_fraction


# Confidence tiers
CONFIDENCE_TIERS = [
    (0.30, "high"),
    (0.15, "medium"),
    (0.05, "low"),
    (0.0, "negligible"),
]


def confidence_tier(probability: float) -> str:
    """Map probability to confidence tier."""
    for threshold, tier in CONFIDENCE_TIERS:
        if probability >= threshold:
            return tier
    return "negligible"


@dataclass
class ScoredCompany:
    """A company with its prediction score."""

    ticker: str
    company_name: str
    probability: float
    confidence: str
    kelly: float
    suggested_weight: float
    contributing_features: dict  # top 5 features with values
    feature_values: dict        # all features


async def score_current_universe(
    db: AsyncSession,
    model: TrainedModel,
    log_fn=None,
) -> list[ScoredCompany]:
    """Score all companies in the universe.

    Args:
        db: Database session.
        model: Trained prediction model.
        log_fn: Optional logging callback.

    Returns:
        List of ScoredCompany, sorted by probability descending.
    """
    log = log_fn or (lambda _: None)

    # Load primary listings with scores (skip duplicate cross-listings)
    result = await db.execute(
        select(Company, CompanyScore)
        .join(CompanyScore, CompanyScore.company_id == Company.id)
        .where(Company.is_primary_listing == True)  # noqa: E712
    )
    rows = result.all()
    log(f"Loaded {len(rows)} companies with scores")

    if not rows:
        return []

    # Build feature vectors
    feature_rows: list[dict[str, float | None]] = []
    company_info: list[tuple[str, str]] = []

    for company, score in rows:
        cd = score.component_data or {}
        market = cd.get("market_metrics", {})
        fundas = cd.get("fundamental_ratios", {})

        # Map stored metrics to prediction features
        # Price-derived features from market_metrics
        pf: dict[str, float | None] = {
            "momentum_3m": market.get("return_3m"),
            "momentum_6m": market.get("return_6m"),
            "momentum_12m": market.get("return_1y"),
            "momentum_24m": None,  # Not stored in CompanyScore
            "momentum_accel": None,
            "relative_strength_12m": None,
            "volatility_6m": None,
            "volatility_12m": market.get("volatility"),
            "vol_trend": None,
            "max_dd_12m": market.get("max_drawdown"),
            "max_dd_24m": None,
            "ma_spread_10": market.get("ma_spread"),
            "ma_spread_20": None,
            "price_range_12m": None,
            "up_months_ratio_12m": None,
        }

        # Fundamental features
        ff = compute_fundamental_features({
            "roe": fundas.get("roe"),
            "net_margin": fundas.get("net_margin"),
            "debt_equity": fundas.get("debt_equity"),
            "revenue_growth": fundas.get("revenue_growth"),
            "fcf_yield": fundas.get("fcf_yield"),
        })

        row = {**pf, **ff}
        feature_rows.append(row)
        company_info.append((company.ticker, company.name))

    # Add cross-sectional ranks
    add_cross_sectional_ranks(feature_rows)

    # Build numpy array
    n = len(feature_rows)
    X = np.full((n, len(ALL_FEATURES)), np.nan)
    for i, row in enumerate(feature_rows):
        for j, feat in enumerate(ALL_FEATURES):
            v = row.get(feat)
            if v is not None:
                X[i, j] = v

    # Predict
    probabilities = model.predict_proba(X)

    # Build results
    scored: list[ScoredCompany] = []
    for i in range(n):
        prob = float(probabilities[i])
        ticker, name = company_info[i]

        # Top contributing features (by importance * value deviation)
        contrib = {}
        for feat_name, importance in list(model.feature_importance.items())[:10]:
            idx = ALL_FEATURES.index(feat_name) if feat_name in ALL_FEATURES else -1
            if idx >= 0 and not np.isnan(X[i, idx]):
                contrib[feat_name] = {
                    "value": round(float(X[i, idx]), 4),
                    "importance": round(importance, 4),
                }
            if len(contrib) >= 5:
                break

        # All feature values
        fvals = {}
        for j, feat in enumerate(ALL_FEATURES):
            if not np.isnan(X[i, j]):
                fvals[feat] = round(float(X[i, j]), 4)

        scored.append(ScoredCompany(
            ticker=ticker,
            company_name=name,
            probability=round(prob, 4),
            confidence=confidence_tier(prob),
            kelly=round(kelly_fraction(prob), 4),
            suggested_weight=0.0,  # Will be set by portfolio builder
            contributing_features=contrib,
            feature_values=fvals,
        ))

    # Sort by probability descending
    scored.sort(key=lambda s: -s.probability)
    log(f"Scored {len(scored)} companies, top: {scored[0].ticker}={scored[0].probability:.3f}" if scored else "No scores")

    return scored
