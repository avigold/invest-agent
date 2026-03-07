"""Tests for candidate_matcher — winner profile computation and scoring."""
from __future__ import annotations

import pytest

from app.screen.candidate_matcher import (
    _metric_proximity,
    _score_company,
    compute_winner_profile,
)


# ---------------------------------------------------------------------------
# _metric_proximity
# ---------------------------------------------------------------------------


class TestMetricProximity:
    def test_at_median_scores_1(self):
        assert _metric_proximity(0.20, 0.15, 0.20, 0.25) == 1.0

    def test_at_p25_scores_high(self):
        score = _metric_proximity(0.15, 0.15, 0.20, 0.25)
        assert 0.3 < score < 0.9  # Not perfect but still good

    def test_far_from_median_scores_low(self):
        score = _metric_proximity(0.60, 0.15, 0.20, 0.25)
        assert score < 0.1

    def test_inverted_below_median_scores_1(self):
        # debt_equity: lower is better
        assert _metric_proximity(0.3, 0.3, 0.5, 0.8, inverted=True) == 1.0

    def test_inverted_above_median_decays(self):
        score = _metric_proximity(1.5, 0.3, 0.5, 0.8, inverted=True)
        assert score < 0.5


# ---------------------------------------------------------------------------
# compute_winner_profile
# ---------------------------------------------------------------------------


class TestWinnerProfile:
    def test_computes_quartiles(self):
        matches = [
            {"fundamentals_at_start": {"roe": 0.10, "net_margin": 0.08}},
            {"fundamentals_at_start": {"roe": 0.20, "net_margin": 0.12}},
            {"fundamentals_at_start": {"roe": 0.25, "net_margin": 0.15}},
            {"fundamentals_at_start": {"roe": 0.30, "net_margin": 0.20}},
        ]

        profile = compute_winner_profile(matches)

        assert "roe" in profile
        assert profile["roe"]["p25"] <= profile["roe"]["median"] <= profile["roe"]["p75"]
        assert profile["roe"]["count"] == 4

    def test_skips_metrics_with_few_values(self):
        matches = [
            {"fundamentals_at_start": {"roe": 0.10}},
            {"fundamentals_at_start": {"roe": 0.20}},
        ]

        profile = compute_winner_profile(matches)

        # Only 2 values — needs >= 3
        assert "roe" not in profile

    def test_handles_missing_fundamentals(self):
        matches = [
            {"fundamentals_at_start": {"roe": 0.10}},
            {"fundamentals_at_start": {}},
            {"fundamentals_at_start": {"roe": 0.20}},
            {"fundamentals_at_start": {"roe": 0.30}},
        ]

        profile = compute_winner_profile(matches)

        assert "roe" in profile
        assert profile["roe"]["count"] == 3

    def test_empty_matches(self):
        assert compute_winner_profile([]) == {}

    def test_excludes_stale_data(self):
        """Fundamentals with _fiscal_gap_days > 3 years should be excluded."""
        matches = [
            {"fundamentals_at_start": {"roe": 0.10, "_fiscal_gap_days": 100}},
            {"fundamentals_at_start": {"roe": 0.20, "_fiscal_gap_days": 200}},
            {"fundamentals_at_start": {"roe": 0.30, "_fiscal_gap_days": 300}},
            # This one is stale (5 years gap)
            {"fundamentals_at_start": {"roe": 0.90, "_fiscal_gap_days": 365 * 5}},
        ]

        profile = compute_winner_profile(matches)

        assert "roe" in profile
        assert profile["roe"]["count"] == 3  # stale one excluded
        assert profile["roe"]["stale_count"] == 1

    def test_only_comparable_metrics(self):
        """Only roe, net_margin, debt_equity are in COMPARABLE_METRICS."""
        matches = [
            {"fundamentals_at_start": {"roe": 0.10, "revenue": 1e9, "fcf": 1e8}},
            {"fundamentals_at_start": {"roe": 0.20, "revenue": 2e9, "fcf": 2e8}},
            {"fundamentals_at_start": {"roe": 0.30, "revenue": 3e9, "fcf": 3e8}},
        ]

        profile = compute_winner_profile(matches)

        assert "roe" in profile
        assert "revenue" not in profile  # not a comparable metric
        assert "fcf" not in profile


# ---------------------------------------------------------------------------
# _score_company
# ---------------------------------------------------------------------------


class TestScoreCompany:
    def test_perfect_match(self):
        profile = {
            "roe": {"p25": 0.15, "median": 0.20, "p75": 0.25, "count": 5},
            "net_margin": {"p25": 0.10, "median": 0.15, "p75": 0.20, "count": 5},
        }
        fundamentals = {"roe": 0.20, "net_margin": 0.15}  # at both medians

        score, factors = _score_company(fundamentals, "45", profile, {"Information Technology"})

        assert score > 0.8
        assert "roe" in factors
        assert "net_margin" in factors
        assert "sector" in factors

    def test_no_match(self):
        profile = {
            "roe": {"p25": 0.15, "median": 0.20, "p75": 0.25, "count": 5},
        }
        fundamentals = {"roe": 0.80}  # Way outside range

        score, factors = _score_company(fundamentals, "55", profile, {"Information Technology"})

        assert score == 0.0
        assert factors == []

    def test_graduated_scoring(self):
        """Companies closer to median should score higher than edge cases."""
        profile = {
            "roe": {"p25": 0.15, "median": 0.20, "p75": 0.25, "count": 5},
            "net_margin": {"p25": 0.10, "median": 0.15, "p75": 0.20, "count": 5},
        }

        # Perfect match at both medians
        score_perfect, _ = _score_company(
            {"roe": 0.20, "net_margin": 0.15}, "", profile, set()
        )
        # Good match but at edges
        score_edge, _ = _score_company(
            {"roe": 0.15, "net_margin": 0.10}, "", profile, set()
        )
        # Poor match well outside range
        score_poor, _ = _score_company(
            {"roe": 0.05, "net_margin": 0.02}, "", profile, set()
        )

        assert score_perfect > score_edge > score_poor

    def test_sector_bonus(self):
        profile = {
            "roe": {"p25": 0.15, "median": 0.20, "p75": 0.25, "count": 5},
            "net_margin": {"p25": 0.10, "median": 0.15, "p75": 0.20, "count": 5},
        }
        # Only ROE matches — net_margin missing → fundamental score < 1.0
        fundamentals = {"roe": 0.20}

        score_with, factors_with = _score_company(
            fundamentals, "45", profile, {"Information Technology"}
        )
        score_without, factors_without = _score_company(
            fundamentals, "55", profile, {"Information Technology"}
        )

        assert score_with > score_without
        assert "sector" in factors_with
        assert "sector" not in factors_without

    def test_missing_fundamentals_penalized(self):
        """Missing data should lower the score (counts as 0 contribution)."""
        profile = {
            "roe": {"p25": 0.15, "median": 0.20, "p75": 0.25, "count": 5},
            "net_margin": {"p25": 0.10, "median": 0.15, "p75": 0.20, "count": 5},
            "debt_equity": {"p25": 0.3, "median": 0.5, "p75": 0.8, "count": 5},
        }

        # Has all 3 metrics matching well
        score_full, _ = _score_company(
            {"roe": 0.20, "net_margin": 0.15, "debt_equity": 0.5}, "", profile, set()
        )
        # Only has 1 metric (other 2 missing = 0 contribution)
        score_sparse, _ = _score_company(
            {"roe": 0.20}, "", profile, set()
        )

        assert score_full > score_sparse

    def test_all_missing_returns_zero(self):
        profile = {
            "roe": {"p25": 0.15, "median": 0.20, "p75": 0.25, "count": 5},
        }
        fundamentals = {}

        score, factors = _score_company(fundamentals, "45", profile, set())

        assert score == 0.0

    def test_debt_equity_inverted(self):
        """Lower debt/equity should score better."""
        profile = {
            "debt_equity": {"p25": 0.3, "median": 0.5, "p75": 0.8, "count": 5},
        }

        score_low, factors_low = _score_company(
            {"debt_equity": 0.3}, "", profile, set()
        )
        score_high, factors_high = _score_company(
            {"debt_equity": 3.0}, "", profile, set()
        )

        assert score_low > score_high
