"""Contrast analysis — compare winners vs non-winners on each feature.

Computes lift (how much more winners had) and separation (Mann-Whitney AUC,
how cleanly the feature divides the groups). High-separation features are
weighted more heavily in candidate scoring.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from app.screen.forward_scanner import Observation


@dataclass
class FeatureContrast:
    """How a single feature differs between two groups."""

    feature: str
    winner_median: float
    winner_p25: float
    winner_p75: float
    non_winner_median: float
    non_winner_p25: float
    non_winner_p75: float
    winner_count: int
    non_winner_count: int
    lift: float          # winner_median / non_winner_median (or difference-based)
    separation: float    # 0-1, Mann-Whitney AUC-based separation
    direction: str       # "higher" or "lower"

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "winner_median": round(self.winner_median, 4),
            "winner_p25": round(self.winner_p25, 4),
            "winner_p75": round(self.winner_p75, 4),
            "non_winner_median": round(self.non_winner_median, 4),
            "non_winner_p25": round(self.non_winner_p25, 4),
            "non_winner_p75": round(self.non_winner_p75, 4),
            "winner_count": self.winner_count,
            "non_winner_count": self.non_winner_count,
            "lift": round(self.lift, 4),
            "separation": round(self.separation, 4),
            "direction": self.direction,
        }


@dataclass
class ContrastProfile:
    """Full contrast analysis across all features."""

    features: list[FeatureContrast]
    winner_count: int
    non_winner_count: int
    total_observations: int

    def to_dict(self) -> dict:
        return {
            "features": [f.to_dict() for f in self.features],
            "winner_count": self.winner_count,
            "non_winner_count": self.non_winner_count,
            "total_observations": self.total_observations,
        }


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

# Minimum observations per group to compute contrast
MIN_GROUP_SIZE = 5


def _quartiles(values: list[float]) -> tuple[float, float, float]:
    """Return (p25, median, p75) for a list of floats."""
    s = sorted(values)
    n = len(s)
    median = statistics.median(s)
    lower = s[: n // 2]
    upper = s[(n + 1) // 2 :]
    p25 = statistics.median(lower) if lower else median
    p75 = statistics.median(upper) if upper else median
    return p25, median, p75


def _mann_whitney_auc(group_a: list[float], group_b: list[float]) -> float:
    """Compute Mann-Whitney U AUC without scipy.

    AUC = P(random a > random b). 0.5 = no separation, 1.0 = perfect.
    We count pairwise comparisons directly.
    """
    na, nb = len(group_a), len(group_b)
    if na == 0 or nb == 0:
        return 0.5

    # Sort group_b for efficient counting
    sorted_b = sorted(group_b)
    count_greater = 0
    count_equal = 0

    for a_val in group_a:
        # Binary search for position in sorted_b
        lo, hi = 0, nb
        while lo < hi:
            mid = (lo + hi) // 2
            if sorted_b[mid] < a_val:
                lo = mid + 1
            else:
                hi = mid
        # lo = number of b values < a_val
        count_greater += lo

        # Count equal values
        eq = lo
        while eq < nb and sorted_b[eq] == a_val:
            eq += 1
        count_equal += eq - lo

    auc = (count_greater + 0.5 * count_equal) / (na * nb)
    return auc


def _compute_lift(winner_median: float, non_winner_median: float) -> float:
    """Compute lift: how much more winners had relative to non-winners."""
    if non_winner_median == 0:
        if winner_median == 0:
            return 1.0
        return float("inf") if winner_median > 0 else float("-inf")
    return winner_median / non_winner_median


def _extract_feature_values(
    observations: Sequence[Observation], feature: str
) -> list[float]:
    """Extract non-None values for a feature from observations."""
    values = []
    for obs in observations:
        val = getattr(obs, feature, None)
        if val is None and feature in ("roe", "net_margin", "debt_equity",
                                        "revenue_growth", "fcf_yield"):
            val = obs.fundamentals.get(feature)
        if val is not None:
            values.append(float(val))
    return values


# Feature list: price-derived features always available
PRICE_FEATURES = [
    "momentum_12m",
    "momentum_6m",
    "volatility_12m",
    "max_dd_12m",
    "ma_spread",
]

FUNDAMENTAL_FEATURES = [
    "roe",
    "net_margin",
    "debt_equity",
    "revenue_growth",
    "fcf_yield",
]

ALL_FEATURES = PRICE_FEATURES + FUNDAMENTAL_FEATURES


# ---------------------------------------------------------------------------
# Main contrast functions
# ---------------------------------------------------------------------------


def compute_contrast(
    observations: list[Observation],
    features: list[str] | None = None,
) -> ContrastProfile:
    """Contrast winners vs non-winners on each feature.

    Args:
        observations: All observations (with labels)
        features: Features to analyze (defaults to ALL_FEATURES)

    Returns: ContrastProfile with per-feature separation and lift
    """
    features = features or ALL_FEATURES

    winners = [o for o in observations if o.label == "winner"]
    non_winners = [o for o in observations if o.label != "winner"]

    feature_contrasts: list[FeatureContrast] = []

    for feat in features:
        w_values = _extract_feature_values(winners, feat)
        nw_values = _extract_feature_values(non_winners, feat)

        if len(w_values) < MIN_GROUP_SIZE or len(nw_values) < MIN_GROUP_SIZE:
            continue

        w_p25, w_med, w_p75 = _quartiles(w_values)
        nw_p25, nw_med, nw_p75 = _quartiles(nw_values)

        lift = _compute_lift(w_med, nw_med)
        auc = _mann_whitney_auc(w_values, nw_values)
        separation = abs(auc - 0.5) * 2  # 0 = no separation, 1 = perfect
        direction = "higher" if auc >= 0.5 else "lower"

        feature_contrasts.append(FeatureContrast(
            feature=feat,
            winner_median=w_med,
            winner_p25=w_p25,
            winner_p75=w_p75,
            non_winner_median=nw_med,
            non_winner_p25=nw_p25,
            non_winner_p75=nw_p75,
            winner_count=len(w_values),
            non_winner_count=len(nw_values),
            lift=lift,
            separation=separation,
            direction=direction,
        ))

    # Sort by separation descending
    feature_contrasts.sort(key=lambda f: f.separation, reverse=True)

    return ContrastProfile(
        features=feature_contrasts,
        winner_count=len(winners),
        non_winner_count=len(non_winners),
        total_observations=len(observations),
    )


def compute_catastrophe_profile(
    observations: list[Observation],
    features: list[str] | None = None,
) -> ContrastProfile:
    """Contrast catastrophes vs non-catastrophes on each feature.

    Same approach as compute_contrast but splitting on catastrophe label.
    """
    features = features or ALL_FEATURES

    catastrophes = [o for o in observations if o.label == "catastrophe"]
    non_catastrophes = [o for o in observations if o.label != "catastrophe"]

    feature_contrasts: list[FeatureContrast] = []

    for feat in features:
        c_values = _extract_feature_values(catastrophes, feat)
        nc_values = _extract_feature_values(non_catastrophes, feat)

        if len(c_values) < MIN_GROUP_SIZE or len(nc_values) < MIN_GROUP_SIZE:
            continue

        c_p25, c_med, c_p75 = _quartiles(c_values)
        nc_p25, nc_med, nc_p75 = _quartiles(nc_values)

        lift = _compute_lift(c_med, nc_med)
        auc = _mann_whitney_auc(c_values, nc_values)
        separation = abs(auc - 0.5) * 2
        direction = "higher" if auc >= 0.5 else "lower"

        feature_contrasts.append(FeatureContrast(
            feature=feat,
            winner_median=c_med,     # reusing field names for catastrophe group
            winner_p25=c_p25,
            winner_p75=c_p75,
            non_winner_median=nc_med,
            non_winner_p25=nc_p25,
            non_winner_p75=nc_p75,
            winner_count=len(c_values),
            non_winner_count=len(nc_values),
            lift=lift,
            separation=separation,
            direction=direction,
        ))

    feature_contrasts.sort(key=lambda f: f.separation, reverse=True)

    return ContrastProfile(
        features=feature_contrasts,
        winner_count=len(catastrophes),
        non_winner_count=len(non_catastrophes),
        total_observations=len(observations),
    )
