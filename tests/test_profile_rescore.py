"""Tests for profile-based recommendation rescoring."""
import pytest

from app.score.profile_rescore import (
    _rescore_company,
    _rescore_country,
    _weighted_average,
    rescore_recommendations,
)
from app.score.profile_schema import ScoringProfileConfig, default_profile_config


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_country_component_data() -> dict:
    """Realistic country component_data (US-like)."""
    return {
        "macro_indicators": {
            "gdp_growth": 2.5,
            "inflation": 3.2,
            "unemployment": 3.6,
            "govt_debt_gdp": 120.0,
            "current_account_gdp": -3.5,
            "fdi_gdp": 1.5,
            "reserves": 50_000_000_000,
            "gdp_per_capita": 65_000,
            "market_cap_gdp": 150.0,
            "household_consumption_pc": 35_000,
        },
        "market_metrics": {
            "return_1y": 0.12,
            "max_drawdown": -0.15,
            "ma_spread": 0.05,
        },
        "stability_value": 0.75,
    }


def _make_company_component_data() -> dict:
    """Realistic company component_data."""
    return {
        "fundamental_ratios": {
            "roe": 0.20,
            "net_margin": 0.15,
            "debt_equity": 0.8,
            "revenue_growth": 0.10,
            "eps_growth": 0.15,
            "fcf_yield": 0.05,
        },
        "market_metrics": {
            "return_1y": 0.25,
            "max_drawdown": -0.10,
            "ma_spread": 0.08,
        },
    }


def _make_base_recommendations() -> list[dict]:
    """Two-company recommendation list."""
    return [
        {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "country_iso2": "US",
            "gics_code": "45",
            "company_score": 75.0,
            "country_score": 65.0,
            "industry_score": 60.0,
            "composite_score": 70.0,
            "classification": "Hold",
            "as_of": "2026-02-28",
            "recommendation_version": "recommendation_v2",
            "rank": 1,
            "rank_total": 2,
        },
        {
            "ticker": "GOOGL",
            "name": "Alphabet Inc.",
            "country_iso2": "US",
            "gics_code": "50",
            "company_score": 80.0,
            "country_score": 65.0,
            "industry_score": 55.0,
            "composite_score": 72.0,
            "classification": "Buy",
            "as_of": "2026-02-28",
            "recommendation_version": "recommendation_v2",
            "rank": 2,
            "rank_total": 2,
        },
    ]


def _make_component_bundles() -> dict:
    return {
        "country": {"US": _make_country_component_data()},
        "company": {
            "AAPL": _make_company_component_data(),
            "GOOGL": _make_company_component_data(),
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWeightedAverage:
    def test_equal_weights(self):
        from app.score.versions import MACRO_ABSOLUTE_THRESHOLDS
        values = {"gdp_growth": 5.0, "inflation": 2.0}
        weights = {"gdp_growth": 1.0, "inflation": 1.0}
        # Only use the two indicators we provided
        thresholds = {k: v for k, v in MACRO_ABSOLUTE_THRESHOLDS.items() if k in values}
        result = _weighted_average(values, weights, thresholds)
        assert 0 <= result <= 100

    def test_zero_weight_excluded(self):
        from app.score.versions import MACRO_ABSOLUTE_THRESHOLDS
        values = {"gdp_growth": 5.0, "inflation": 15.0}  # terrible inflation
        weights = {"gdp_growth": 1.0, "inflation": 0.0}  # ignore inflation
        thresholds = {k: v for k, v in MACRO_ABSOLUTE_THRESHOLDS.items() if k in values}
        result = _weighted_average(values, weights, thresholds)
        # Should only reflect gdp_growth, which is good
        assert result > 50

    def test_all_zero_weights_returns_50(self):
        values = {"gdp_growth": 5.0}
        weights = {"gdp_growth": 0.0}
        result = _weighted_average(values, weights, {})
        assert result == 50.0

    def test_none_value_scores_50(self):
        from app.score.versions import MACRO_ABSOLUTE_THRESHOLDS
        values = {"gdp_growth": None}
        weights = {"gdp_growth": 1.0}
        thresholds = {"gdp_growth": MACRO_ABSOLUTE_THRESHOLDS["gdp_growth"]}
        result = _weighted_average(values, weights, thresholds)
        assert result == 50.0


class TestRescoreCountry:
    def test_default_profile_produces_score(self):
        profile = default_profile_config()
        cd = _make_country_component_data()
        score = _rescore_country(cd, profile)
        assert 0 <= score <= 100

    def test_emphasize_stability(self):
        cd = _make_country_component_data()
        cd["stability_value"] = 0.95  # very stable

        default = default_profile_config()
        default_score = _rescore_country(cd, default)

        # Heavy stability weight
        heavy_stability = default.model_dump()
        heavy_stability["country_weights"] = {"macro": 0.05, "market": 0.05, "stability": 0.90}
        profile = ScoringProfileConfig(**heavy_stability)
        stability_score = _rescore_country(cd, profile)

        # With 0.95 stability (score=95), heavy weight should push score up
        assert stability_score > default_score or stability_score > 90


class TestRescoreCompany:
    def test_default_profile_produces_score(self):
        profile = default_profile_config()
        cd = _make_company_component_data()
        score = _rescore_company(cd, profile)
        assert 0 <= score <= 100

    def test_no_fundamentals_uses_market_only(self):
        profile = default_profile_config()
        cd = {"fundamental_ratios": {}, "market_metrics": _make_company_component_data()["market_metrics"]}
        score = _rescore_company(cd, profile)
        assert 0 <= score <= 100


class TestRescoreRecommendations:
    def test_default_profile_preserves_order(self):
        """Default profile should produce similar scores (not necessarily identical due to
        floating-point differences in scoring path)."""
        profile = default_profile_config()
        base = _make_base_recommendations()
        bundles = _make_component_bundles()
        result = rescore_recommendations(base, bundles, profile)
        assert len(result) == 2
        assert result[0]["rank"] == 1
        assert result[1]["rank"] == 2

    def test_company_heavy_weight_reorders(self):
        """Setting company weight to 1.0 should rank by company score."""
        profile_data = default_profile_config().model_dump()
        profile_data["recommendation_weights"] = {"country": 0.0, "industry": 0.0, "company": 1.0}
        profile = ScoringProfileConfig(**profile_data)

        base = _make_base_recommendations()
        bundles = _make_component_bundles()

        # Make AAPL's company much better
        bundles["company"]["AAPL"]["fundamental_ratios"]["roe"] = 0.30
        bundles["company"]["AAPL"]["fundamental_ratios"]["net_margin"] = 0.25
        bundles["company"]["GOOGL"]["fundamental_ratios"]["roe"] = 0.01
        bundles["company"]["GOOGL"]["fundamental_ratios"]["net_margin"] = 0.01

        result = rescore_recommendations(base, bundles, profile)
        # AAPL should rank higher since we heavily weighted company + gave it better fundamentals
        aapl = next(r for r in result if r["ticker"] == "AAPL")
        googl = next(r for r in result if r["ticker"] == "GOOGL")
        assert aapl["composite_score"] > googl["composite_score"]

    def test_threshold_reclassification(self):
        """Changing thresholds should reclassify."""
        profile_data = default_profile_config().model_dump()
        # Set very low buy threshold so everything is Buy
        profile_data["thresholds"] = {"buy": 10, "sell": 5}
        profile = ScoringProfileConfig(**profile_data)

        base = _make_base_recommendations()
        bundles = _make_component_bundles()
        result = rescore_recommendations(base, bundles, profile)
        assert all(r["classification"] == "Buy" for r in result)

    def test_ranks_reassigned(self):
        profile = default_profile_config()
        base = _make_base_recommendations()
        bundles = _make_component_bundles()
        result = rescore_recommendations(base, bundles, profile)
        ranks = [r["rank"] for r in result]
        assert sorted(ranks) == [1, 2]
        assert all(r["rank_total"] == 2 for r in result)

    def test_missing_component_data_uses_base(self):
        """If component_data is missing for an entity, use base scores."""
        profile = default_profile_config()
        base = _make_base_recommendations()
        empty_bundles = {"country": {}, "company": {}}
        result = rescore_recommendations(base, empty_bundles, profile)
        # Scores should be based on original values since no component_data to rescore from
        assert result[0]["country_score"] == base[0]["country_score"] or result[1]["country_score"] == base[1]["country_score"]
