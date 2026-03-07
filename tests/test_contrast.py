"""Tests for contrast — winner vs non-winner analysis."""
from __future__ import annotations

from datetime import date

import pytest

from app.screen.contrast import (
    ContrastProfile,
    FeatureContrast,
    _mann_whitney_auc,
    _quartiles,
    compute_catastrophe_profile,
    compute_contrast,
)
from app.screen.forward_scanner import Observation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_obs(
    label: str = "normal",
    momentum_12m: float | None = None,
    volatility_12m: float | None = None,
    ma_spread: float | None = None,
    momentum_6m: float | None = None,
    max_dd_12m: float | None = None,
    fundamentals: dict | None = None,
) -> Observation:
    """Create a minimal Observation for testing."""
    return Observation(
        ticker="TEST",
        name="Test",
        country_iso2="US",
        gics_code="45",
        obs_date=date(2020, 1, 1),
        forward_return=1.0 if label == "winner" else 0.1,
        forward_max_dd=-0.1 if label != "catastrophe" else -0.85,
        label=label,
        momentum_12m=momentum_12m,
        momentum_6m=momentum_6m,
        volatility_12m=volatility_12m,
        max_dd_12m=max_dd_12m,
        ma_spread=ma_spread,
        obs_price=50.0,
        fundamentals=fundamentals or {},
    )


# ---------------------------------------------------------------------------
# _quartiles
# ---------------------------------------------------------------------------


class TestQuartiles:
    def test_basic(self):
        p25, med, p75 = _quartiles([1, 2, 3, 4, 5])
        assert med == 3
        assert p25 == 1.5  # median of [1, 2]
        assert p75 == 4.5  # median of [4, 5]

    def test_even_count(self):
        p25, med, p75 = _quartiles([1, 2, 3, 4])
        assert med == 2.5
        assert p25 <= med <= p75

    def test_single_value(self):
        p25, med, p75 = _quartiles([5.0])
        assert p25 == med == p75 == 5.0

    def test_two_values(self):
        p25, med, p75 = _quartiles([1.0, 3.0])
        assert med == 2.0


# ---------------------------------------------------------------------------
# _mann_whitney_auc
# ---------------------------------------------------------------------------


class TestMannWhitneyAUC:
    def test_perfect_separation(self):
        # All A values > all B values
        a = [10.0, 11.0, 12.0]
        b = [1.0, 2.0, 3.0]
        auc = _mann_whitney_auc(a, b)
        assert auc == 1.0

    def test_no_separation(self):
        # Identical distributions
        a = [1.0, 2.0, 3.0, 4.0, 5.0]
        b = [1.0, 2.0, 3.0, 4.0, 5.0]
        auc = _mann_whitney_auc(a, b)
        assert abs(auc - 0.5) < 0.01

    def test_reversed_separation(self):
        # All A values < all B values
        a = [1.0, 2.0, 3.0]
        b = [10.0, 11.0, 12.0]
        auc = _mann_whitney_auc(a, b)
        assert auc == 0.0

    def test_partial_overlap(self):
        a = [5.0, 6.0, 7.0, 8.0]
        b = [1.0, 2.0, 3.0, 4.0]
        auc = _mann_whitney_auc(a, b)
        assert auc == 1.0  # Still perfect here

    def test_mixed_overlap(self):
        a = [3.0, 5.0, 7.0, 9.0]
        b = [2.0, 4.0, 6.0, 8.0]
        auc = _mann_whitney_auc(a, b)
        # A tends to be higher but with overlap
        assert 0.5 < auc < 1.0

    def test_empty_group_returns_half(self):
        assert _mann_whitney_auc([], [1.0, 2.0]) == 0.5
        assert _mann_whitney_auc([1.0, 2.0], []) == 0.5


# ---------------------------------------------------------------------------
# compute_contrast
# ---------------------------------------------------------------------------


class TestComputeContrast:
    def _make_observations(self) -> list[Observation]:
        """Create a set of observations with clear winner/non-winner separation."""
        obs = []
        # Winners: high momentum, low volatility
        for i in range(10):
            obs.append(_make_obs(
                label="winner",
                momentum_12m=0.50 + i * 0.05,
                volatility_12m=0.15 + i * 0.01,
                ma_spread=0.10 + i * 0.02,
            ))
        # Non-winners: low momentum, high volatility
        for i in range(40):
            obs.append(_make_obs(
                label="normal",
                momentum_12m=0.05 + i * 0.01,
                volatility_12m=0.30 + i * 0.01,
                ma_spread=-0.05 + i * 0.005,
            ))
        return obs

    def test_returns_contrast_profile(self):
        obs = self._make_observations()
        profile = compute_contrast(obs, features=["momentum_12m", "volatility_12m"])

        assert isinstance(profile, ContrastProfile)
        assert profile.winner_count == 10
        assert profile.non_winner_count == 40
        assert profile.total_observations == 50

    def test_features_sorted_by_separation(self):
        obs = self._make_observations()
        profile = compute_contrast(obs, features=["momentum_12m", "volatility_12m", "ma_spread"])

        assert len(profile.features) > 0
        separations = [f.separation for f in profile.features]
        assert separations == sorted(separations, reverse=True)

    def test_winner_momentum_higher(self):
        obs = self._make_observations()
        profile = compute_contrast(obs, features=["momentum_12m"])

        assert len(profile.features) == 1
        fc = profile.features[0]
        assert fc.winner_median > fc.non_winner_median
        assert fc.direction == "higher"
        assert fc.lift > 1.0

    def test_separation_score_meaningful(self):
        obs = self._make_observations()
        profile = compute_contrast(obs, features=["momentum_12m"])

        fc = profile.features[0]
        assert fc.separation > 0.3  # Should have meaningful separation

    def test_skips_features_with_insufficient_data(self):
        # Only 3 winners — below MIN_GROUP_SIZE of 5
        obs = []
        for i in range(3):
            obs.append(_make_obs(label="winner", momentum_12m=0.5))
        for i in range(20):
            obs.append(_make_obs(label="normal", momentum_12m=0.1))

        profile = compute_contrast(obs, features=["momentum_12m"])
        assert len(profile.features) == 0

    def test_handles_none_values(self):
        obs = []
        # Winners with momentum
        for i in range(8):
            obs.append(_make_obs(label="winner", momentum_12m=0.5))
        # Some winners without momentum
        for i in range(2):
            obs.append(_make_obs(label="winner", momentum_12m=None))
        # Non-winners
        for i in range(30):
            obs.append(_make_obs(label="normal", momentum_12m=0.1))

        profile = compute_contrast(obs, features=["momentum_12m"])
        assert len(profile.features) == 1
        assert profile.features[0].winner_count == 8  # Only non-None

    def test_serialization(self):
        obs = self._make_observations()
        profile = compute_contrast(obs, features=["momentum_12m"])

        d = profile.to_dict()
        assert isinstance(d, dict)
        assert "features" in d
        assert "winner_count" in d
        assert len(d["features"]) > 0
        assert "feature" in d["features"][0]
        assert "lift" in d["features"][0]
        assert "separation" in d["features"][0]

    def test_fundamental_features_from_dict(self):
        """Fundamental features should be extracted from obs.fundamentals dict."""
        obs = []
        for i in range(8):
            obs.append(_make_obs(
                label="winner",
                momentum_12m=0.5,
                fundamentals={"roe": 0.25 + i * 0.01},
            ))
        for i in range(30):
            obs.append(_make_obs(
                label="normal",
                momentum_12m=0.1,
                fundamentals={"roe": 0.10 + i * 0.005},
            ))

        profile = compute_contrast(obs, features=["roe"])
        assert len(profile.features) == 1
        assert profile.features[0].feature == "roe"
        assert profile.features[0].winner_median > profile.features[0].non_winner_median


# ---------------------------------------------------------------------------
# compute_catastrophe_profile
# ---------------------------------------------------------------------------


class TestCatastropheProfile:
    def _make_observations(self) -> list[Observation]:
        obs = []
        # Catastrophes: high volatility, negative momentum
        for i in range(8):
            obs.append(_make_obs(
                label="catastrophe",
                momentum_12m=-0.20 - i * 0.05,
                volatility_12m=0.50 + i * 0.05,
                ma_spread=-0.15 - i * 0.02,
            ))
        # Non-catastrophes: moderate volatility, positive momentum
        for i in range(40):
            obs.append(_make_obs(
                label="normal",
                momentum_12m=0.10 + i * 0.01,
                volatility_12m=0.20 + i * 0.005,
                ma_spread=0.05 + i * 0.005,
            ))
        return obs

    def test_returns_profile(self):
        obs = self._make_observations()
        profile = compute_catastrophe_profile(obs, features=["momentum_12m", "volatility_12m"])

        assert isinstance(profile, ContrastProfile)
        assert profile.winner_count == 8   # catastrophes
        assert profile.non_winner_count == 40

    def test_catastrophe_momentum_lower(self):
        obs = self._make_observations()
        profile = compute_catastrophe_profile(obs, features=["momentum_12m"])

        assert len(profile.features) == 1
        fc = profile.features[0]
        # Catastrophes had negative momentum
        assert fc.winner_median < fc.non_winner_median
        assert fc.direction == "lower"

    def test_catastrophe_volatility_higher(self):
        obs = self._make_observations()
        profile = compute_catastrophe_profile(obs, features=["volatility_12m"])

        fc = profile.features[0]
        assert fc.winner_median > fc.non_winner_median
        assert fc.direction == "higher"

    def test_separation_meaningful(self):
        obs = self._make_observations()
        profile = compute_catastrophe_profile(
            obs, features=["momentum_12m", "volatility_12m"]
        )

        for fc in profile.features:
            assert fc.separation > 0.3
