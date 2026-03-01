"""Scoring profile configuration schema and defaults."""
from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, model_validator

from app.score.versions import (
    COMPANY_WEIGHTS,
    COUNTRY_WEIGHTS,
    FUNDAMENTAL_ABSOLUTE_THRESHOLDS,
    MACRO_ABSOLUTE_THRESHOLDS,
    MARKET_ABSOLUTE_THRESHOLDS,
    RECOMMENDATION_THRESHOLDS,
    RECOMMENDATION_WEIGHTS,
)

# Canonical indicator/metric names (the only keys allowed)
MACRO_INDICATOR_NAMES = set(MACRO_ABSOLUTE_THRESHOLDS.keys())
MARKET_METRIC_NAMES = set(MARKET_ABSOLUTE_THRESHOLDS.keys())
FUNDAMENTAL_RATIO_NAMES = set(FUNDAMENTAL_ABSOLUTE_THRESHOLDS.keys())

_TOLERANCE = 0.02  # floating-point tolerance for sum-to-1 checks


class ScoringProfileConfig(BaseModel):
    """Full scoring profile configuration.

    All weight groups that must sum to 1.0 are validated.
    Indicator/metric weights are relative (normalized at scoring time).
    """

    recommendation_weights: dict[str, float]  # country, industry, company
    thresholds: dict[str, float]  # buy, sell
    country_weights: dict[str, float]  # macro, market, stability
    country_macro_indicator_weights: dict[str, float]  # 10 indicators
    country_market_metric_weights: dict[str, float]  # 3 metrics
    company_weights: dict[str, float]  # fundamental, market
    company_fundamental_ratio_weights: dict[str, float]  # 6 ratios
    company_market_metric_weights: dict[str, float]  # 3 metrics

    @model_validator(mode="after")
    def validate_all(self) -> ScoringProfileConfig:
        # Recommendation weights
        _validate_sum_to_one(
            self.recommendation_weights,
            {"country", "industry", "company"},
            "recommendation_weights",
        )

        # Thresholds
        if set(self.thresholds.keys()) != {"buy", "sell"}:
            raise ValueError("thresholds must have keys 'buy' and 'sell'")
        if self.thresholds["buy"] <= self.thresholds["sell"]:
            raise ValueError("buy threshold must be greater than sell threshold")

        # Country weights
        _validate_sum_to_one(
            self.country_weights,
            {"macro", "market", "stability"},
            "country_weights",
        )

        # Company weights
        _validate_sum_to_one(
            self.company_weights,
            {"fundamental", "market"},
            "company_weights",
        )

        # Indicator/metric weights: must have correct keys, all >= 0, at least one > 0
        _validate_relative_weights(
            self.country_macro_indicator_weights,
            MACRO_INDICATOR_NAMES,
            "country_macro_indicator_weights",
        )
        _validate_relative_weights(
            self.country_market_metric_weights,
            MARKET_METRIC_NAMES,
            "country_market_metric_weights",
        )
        _validate_relative_weights(
            self.company_fundamental_ratio_weights,
            FUNDAMENTAL_RATIO_NAMES,
            "company_fundamental_ratio_weights",
        )
        _validate_relative_weights(
            self.company_market_metric_weights,
            MARKET_METRIC_NAMES,
            "company_market_metric_weights",
        )

        return self


def _validate_sum_to_one(
    weights: dict[str, float], required_keys: set[str], field_name: str
) -> None:
    if set(weights.keys()) != required_keys:
        raise ValueError(f"{field_name} must have keys {sorted(required_keys)}")
    for k, v in weights.items():
        if v < 0:
            raise ValueError(f"{field_name}['{k}'] must be >= 0")
    total = sum(weights.values())
    if not math.isclose(total, 1.0, abs_tol=_TOLERANCE):
        raise ValueError(f"{field_name} must sum to 1.0 (got {total:.4f})")


def _validate_relative_weights(
    weights: dict[str, float], allowed_keys: set[str], field_name: str
) -> None:
    if set(weights.keys()) != allowed_keys:
        raise ValueError(f"{field_name} must have keys {sorted(allowed_keys)}")
    for k, v in weights.items():
        if v < 0:
            raise ValueError(f"{field_name}['{k}'] must be >= 0")
    if all(v == 0 for v in weights.values()):
        raise ValueError(f"{field_name} must have at least one weight > 0")


def default_profile_config() -> ScoringProfileConfig:
    """Build a ScoringProfileConfig from system default constants."""
    return ScoringProfileConfig(
        recommendation_weights=dict(RECOMMENDATION_WEIGHTS),
        thresholds=dict(RECOMMENDATION_THRESHOLDS),
        country_weights=dict(COUNTRY_WEIGHTS),
        country_macro_indicator_weights={k: 1.0 for k in MACRO_ABSOLUTE_THRESHOLDS},
        country_market_metric_weights={k: 1.0 for k in MARKET_ABSOLUTE_THRESHOLDS},
        company_weights=dict(COMPANY_WEIGHTS),
        company_fundamental_ratio_weights={k: 1.0 for k in FUNDAMENTAL_ABSOLUTE_THRESHOLDS},
        company_market_metric_weights={k: 1.0 for k in MARKET_ABSOLUTE_THRESHOLDS},
    )


def merge_with_defaults(partial: dict[str, Any]) -> dict[str, Any]:
    """Merge a partial config dict with system defaults.

    Any missing top-level keys are filled from default_profile_config().
    """
    defaults = default_profile_config().model_dump()
    merged = dict(defaults)
    for key, value in partial.items():
        if key in merged and isinstance(value, dict):
            merged[key] = {**defaults[key], **value}
        else:
            merged[key] = value
    return merged
