"""Tests for score_from_features utility."""
from __future__ import annotations

from app.score.feature_scorer import score_from_features


class TestScoreFromFeatures:
    def test_empty_features_returns_neutral(self):
        result = score_from_features({})
        assert result["fundamental_score"] == 50.0
        assert result["market_score"] == 50.0
        assert result["company_score"] == 50.0
        assert result["classification"] == "Hold"

    def test_strong_fundamentals_and_market_returns_buy(self):
        features = {
            "roe": 0.30,
            "net_margin": 0.25,
            "debt_equity": 0.5,
            "revenue_growth": 0.30,
            "eps_growth": 0.50,
            "fcf_yield": 0.20,
            "momentum_12m": 0.40,
            "max_dd_12m": 0.0,
            "ma_spread_20": 0.20,
        }
        result = score_from_features(features)
        assert result["company_score"] > 70
        assert result["classification"] == "Buy"

    def test_weak_fundamentals_and_market_returns_sell(self):
        features = {
            "roe": -0.20,
            "net_margin": -0.15,
            "debt_equity": 5.0,
            "revenue_growth": -0.20,
            "eps_growth": -0.30,
            "fcf_yield": -0.10,
            "momentum_12m": -0.40,
            "max_dd_12m": -0.50,
            "ma_spread_20": -0.20,
        }
        result = score_from_features(features)
        assert result["company_score"] < 40
        assert result["classification"] == "Sell"

    def test_partial_features_handled(self):
        features = {"roe": 0.25, "momentum_12m": 0.20}
        result = score_from_features(features)
        assert result["fundamental_ratios"]["roe"] == 0.25
        assert result["fundamental_ratios"]["net_margin"] is None
        assert result["market_metrics"]["return_1y"] == 0.20
        assert result["market_metrics"]["max_drawdown"] is None
        assert result["classification"] in ("Buy", "Hold", "Sell")

    def test_no_fundamentals_uses_market_only(self):
        features = {
            "momentum_12m": 0.40,
            "max_dd_12m": 0.0,
            "ma_spread_20": 0.20,
        }
        result = score_from_features(features)
        # With no fundamentals, company_score = market_score * 1.0
        assert result["company_score"] == result["market_score"]

    def test_returns_all_keys(self):
        result = score_from_features({"roe": 0.15})
        assert set(result.keys()) == {
            "fundamental_score", "market_score", "company_score",
            "classification", "fundamental_ratios", "market_metrics",
        }

    def test_market_feature_mapping(self):
        features = {"momentum_12m": 0.10, "max_dd_12m": -0.25, "ma_spread_20": 0.05}
        result = score_from_features(features)
        assert result["market_metrics"]["return_1y"] == 0.10
        assert result["market_metrics"]["max_drawdown"] == -0.25
        assert result["market_metrics"]["ma_spread"] == 0.05

    def test_string_values_converted_to_float(self):
        # feature_values may have been serialised; ensure conversion
        features = {"roe": "0.25", "momentum_12m": "0.10"}
        result = score_from_features(features)
        assert result["fundamental_ratios"]["roe"] == 0.25
        assert result["market_metrics"]["return_1y"] == 0.10
