"""Tests for recommendation computation — classify, composite formula, defaults."""
from __future__ import annotations

import pytest

from app.score.recommendations import classify
from app.score.versions import (
    RECOMMENDATION_THRESHOLDS,
    RECOMMENDATION_WEIGHTS,
)


# ---------------------------------------------------------------------------
# classify() tests
# ---------------------------------------------------------------------------

class TestClassify:
    def test_buy_above_threshold(self):
        assert classify(75.0) == "Buy"
        assert classify(90.0) == "Buy"
        assert classify(100.0) == "Buy"

    def test_sell_below_threshold(self):
        assert classify(30.0) == "Sell"
        assert classify(10.0) == "Sell"
        assert classify(0.0) == "Sell"

    def test_hold_in_range(self):
        assert classify(50.0) == "Hold"
        assert classify(55.0) == "Hold"
        assert classify(65.0) == "Hold"

    def test_boundary_70_is_hold(self):
        """Exactly 70 is Hold (need >70 for Buy)."""
        assert classify(70.0) == "Hold"

    def test_boundary_40_is_hold(self):
        """Exactly 40 is Hold (need <40 for Sell)."""
        assert classify(40.0) == "Hold"

    def test_boundary_70_01_is_buy(self):
        assert classify(70.01) == "Buy"

    def test_boundary_39_99_is_sell(self):
        assert classify(39.99) == "Sell"


# ---------------------------------------------------------------------------
# Composite formula tests
# ---------------------------------------------------------------------------

class TestCompositeFormula:
    def test_weights_sum_to_one(self):
        total = sum(RECOMMENDATION_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_composite_calculation(self):
        """20% country + 20% industry + 60% company."""
        w = RECOMMENDATION_WEIGHTS
        country_score = 80.0
        industry_score = 60.0
        company_score = 70.0
        composite = (
            w["country"] * country_score
            + w["industry"] * industry_score
            + w["company"] * company_score
        )
        expected = 0.20 * 80.0 + 0.20 * 60.0 + 0.60 * 70.0
        assert composite == pytest.approx(expected)
        assert composite == pytest.approx(70.0)

    def test_all_scores_same_returns_same(self):
        """When all three scores are the same, composite equals that score."""
        w = RECOMMENDATION_WEIGHTS
        score = 55.0
        composite = w["country"] * score + w["industry"] * score + w["company"] * score
        assert composite == pytest.approx(55.0)

    def test_company_dominates(self):
        """Company score has 60% weight, should dominate the result."""
        w = RECOMMENDATION_WEIGHTS
        # Low country/industry, high company
        composite = w["country"] * 20.0 + w["industry"] * 20.0 + w["company"] * 90.0
        # 0.20*20 + 0.20*20 + 0.60*90 = 4 + 4 + 54 = 62.0
        assert composite == pytest.approx(62.0)

    def test_default_scores_produce_hold(self):
        """When all scores default to 50.0, composite = 50.0 (Hold)."""
        w = RECOMMENDATION_WEIGHTS
        composite = w["country"] * 50.0 + w["industry"] * 50.0 + w["company"] * 50.0
        assert composite == pytest.approx(50.0)
        assert classify(composite) == "Hold"

    def test_determinism(self):
        """Same inputs always produce same output."""
        w = RECOMMENDATION_WEIGHTS
        c1 = w["country"] * 72.0 + w["industry"] * 65.0 + w["company"] * 78.0
        c2 = w["country"] * 72.0 + w["industry"] * 65.0 + w["company"] * 78.0
        assert c1 == c2

    def test_thresholds_are_correct(self):
        assert RECOMMENDATION_THRESHOLDS["buy"] == 70
        assert RECOMMENDATION_THRESHOLDS["sell"] == 40
