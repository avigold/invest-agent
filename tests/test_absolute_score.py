"""Tests for the absolute_score() function."""
from __future__ import annotations

import pytest

from app.score.absolute import absolute_score


class TestAbsoluteScore:
    def test_linear_interpolation_midpoint(self):
        assert absolute_score(5.0, 0.0, 10.0) == pytest.approx(50.0)

    def test_linear_interpolation_floor(self):
        assert absolute_score(0.0, 0.0, 10.0) == pytest.approx(0.0)

    def test_linear_interpolation_ceiling(self):
        assert absolute_score(10.0, 0.0, 10.0) == pytest.approx(100.0)

    def test_linear_interpolation_quarter(self):
        assert absolute_score(2.5, 0.0, 10.0) == pytest.approx(25.0)

    def test_clamp_below_floor(self):
        assert absolute_score(-5.0, 0.0, 10.0) == pytest.approx(0.0)

    def test_clamp_above_ceiling(self):
        assert absolute_score(15.0, 0.0, 10.0) == pytest.approx(100.0)

    def test_none_returns_50(self):
        assert absolute_score(None, 0.0, 10.0) == pytest.approx(50.0)

    def test_floor_equals_ceiling_returns_50(self):
        assert absolute_score(5.0, 5.0, 5.0) == pytest.approx(50.0)

    def test_higher_is_better_false(self):
        """Lower value should score higher when higher_is_better=False."""
        score_low = absolute_score(2.0, 1.0, 15.0, higher_is_better=False)
        score_high = absolute_score(10.0, 1.0, 15.0, higher_is_better=False)
        assert score_low > score_high

    def test_higher_is_better_false_boundaries(self):
        """Floor maps to 100 and ceiling maps to 0 when higher_is_better=False."""
        # inflation: floor=1 (best, 100), ceiling=15 (worst, 0)
        assert absolute_score(1.0, 1.0, 15.0, higher_is_better=False) == pytest.approx(100.0)
        assert absolute_score(15.0, 1.0, 15.0, higher_is_better=False) == pytest.approx(0.0)

    def test_known_macro_gdp_growth(self):
        """GDP growth 3% with floor=-2, ceiling=8 → 50."""
        assert absolute_score(3.0, -2.0, 8.0) == pytest.approx(50.0)

    def test_known_macro_gdp_growth_at_ceiling(self):
        """GDP growth 8% → 100."""
        assert absolute_score(8.0, -2.0, 8.0) == pytest.approx(100.0)

    def test_known_macro_inflation(self):
        """Inflation 2% with floor=1, ceiling=15, lower_is_better → ~92.9."""
        # Swap: floor=15, ceiling=1; ratio = (2-15)/(1-15) = -13/-14 ≈ 0.929
        score = absolute_score(2.0, 1.0, 15.0, higher_is_better=False)
        assert score == pytest.approx(92.86, abs=0.01)

    def test_known_macro_unemployment(self):
        """Unemployment 4% with floor=2, ceiling=15, lower_is_better → ~84.6."""
        # Swap: floor=15, ceiling=2; ratio = (4-15)/(2-15) = -11/-13 ≈ 0.846
        score = absolute_score(4.0, 2.0, 15.0, higher_is_better=False)
        assert score == pytest.approx(84.62, abs=0.01)

    def test_known_fundamental_debt_equity(self):
        """D/E of 1.0 with floor=0, ceiling=5, lower_is_better → 80."""
        # Swap: floor=5, ceiling=0; ratio = (1-5)/(0-5) = -4/-5 = 0.8
        score = absolute_score(1.0, 0.0, 5.0, higher_is_better=False)
        assert score == pytest.approx(80.0)

    def test_universe_independence(self):
        """Same inputs always produce same output — no universe dependency."""
        s1 = absolute_score(0.15, -0.20, 0.30)
        s2 = absolute_score(0.15, -0.20, 0.30)
        assert s1 == s2

    def test_negative_floor_positive_ceiling(self):
        """Common pattern: floor=-0.20, ceiling=0.30 for growth metrics."""
        assert absolute_score(0.05, -0.20, 0.30) == pytest.approx(50.0)
        assert absolute_score(-0.20, -0.20, 0.30) == pytest.approx(0.0)
        assert absolute_score(0.30, -0.20, 0.30) == pytest.approx(100.0)
