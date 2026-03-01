"""Tests for scoring profile schema validation and defaults."""
import pytest

from app.score.profile_schema import (
    ScoringProfileConfig,
    default_profile_config,
    merge_with_defaults,
)


class TestDefaultProfileConfig:
    def test_default_passes_validation(self):
        config = default_profile_config()
        assert isinstance(config, ScoringProfileConfig)

    def test_recommendation_weights_sum_to_one(self):
        config = default_profile_config()
        total = sum(config.recommendation_weights.values())
        assert abs(total - 1.0) < 0.01

    def test_country_weights_sum_to_one(self):
        config = default_profile_config()
        total = sum(config.country_weights.values())
        assert abs(total - 1.0) < 0.01

    def test_company_weights_sum_to_one(self):
        config = default_profile_config()
        total = sum(config.company_weights.values())
        assert abs(total - 1.0) < 0.01

    def test_default_thresholds(self):
        config = default_profile_config()
        assert config.thresholds["buy"] > config.thresholds["sell"]

    def test_all_macro_indicators_present(self):
        config = default_profile_config()
        assert len(config.country_macro_indicator_weights) == 10

    def test_all_fundamental_ratios_present(self):
        config = default_profile_config()
        assert len(config.company_fundamental_ratio_weights) == 6

    def test_all_market_metrics_present(self):
        config = default_profile_config()
        assert len(config.country_market_metric_weights) == 3
        assert len(config.company_market_metric_weights) == 3


class TestValidation:
    def _base(self) -> dict:
        return default_profile_config().model_dump()

    def test_valid_custom_weights(self):
        data = self._base()
        data["recommendation_weights"] = {"country": 0.10, "industry": 0.10, "company": 0.80}
        config = ScoringProfileConfig(**data)
        assert config.recommendation_weights["company"] == 0.80

    def test_recommendation_weights_dont_sum_to_one(self):
        data = self._base()
        data["recommendation_weights"] = {"country": 0.50, "industry": 0.50, "company": 0.50}
        with pytest.raises(ValueError, match="sum to 1.0"):
            ScoringProfileConfig(**data)

    def test_negative_weight_rejected(self):
        data = self._base()
        data["recommendation_weights"] = {"country": -0.10, "industry": 0.30, "company": 0.80}
        with pytest.raises(ValueError, match="must be >= 0"):
            ScoringProfileConfig(**data)

    def test_buy_less_than_sell_rejected(self):
        data = self._base()
        data["thresholds"] = {"buy": 30, "sell": 50}
        with pytest.raises(ValueError, match="buy threshold must be greater"):
            ScoringProfileConfig(**data)

    def test_buy_equal_sell_rejected(self):
        data = self._base()
        data["thresholds"] = {"buy": 50, "sell": 50}
        with pytest.raises(ValueError, match="buy threshold must be greater"):
            ScoringProfileConfig(**data)

    def test_unknown_indicator_key_rejected(self):
        data = self._base()
        data["country_macro_indicator_weights"]["fake_indicator"] = 1.0
        with pytest.raises(ValueError, match="country_macro_indicator_weights must have keys"):
            ScoringProfileConfig(**data)

    def test_missing_indicator_key_rejected(self):
        data = self._base()
        del data["country_macro_indicator_weights"]["gdp_growth"]
        with pytest.raises(ValueError, match="country_macro_indicator_weights must have keys"):
            ScoringProfileConfig(**data)

    def test_all_zero_indicator_weights_rejected(self):
        data = self._base()
        for k in data["country_macro_indicator_weights"]:
            data["country_macro_indicator_weights"][k] = 0.0
        with pytest.raises(ValueError, match="at least one weight > 0"):
            ScoringProfileConfig(**data)

    def test_country_weights_wrong_keys(self):
        data = self._base()
        data["country_weights"] = {"macro": 0.50, "market": 0.50}
        with pytest.raises(ValueError, match="country_weights must have keys"):
            ScoringProfileConfig(**data)

    def test_company_weights_dont_sum_to_one(self):
        data = self._base()
        data["company_weights"] = {"fundamental": 0.80, "market": 0.80}
        with pytest.raises(ValueError, match="sum to 1.0"):
            ScoringProfileConfig(**data)

    def test_tolerance_for_floating_point(self):
        """Weights that are very close to 1.0 should pass."""
        data = self._base()
        data["recommendation_weights"] = {
            "country": 0.333,
            "industry": 0.333,
            "company": 0.334,
        }
        config = ScoringProfileConfig(**data)
        assert config is not None


class TestMergeWithDefaults:
    def test_empty_partial_returns_defaults(self):
        merged = merge_with_defaults({})
        defaults = default_profile_config().model_dump()
        assert merged == defaults

    def test_partial_recommendation_weights(self):
        partial = {
            "recommendation_weights": {"country": 0.10, "industry": 0.10, "company": 0.80},
        }
        merged = merge_with_defaults(partial)
        assert merged["recommendation_weights"]["company"] == 0.80
        # Other sections should be defaults
        assert len(merged["country_macro_indicator_weights"]) == 10

    def test_partial_indicator_weights(self):
        partial = {
            "country_macro_indicator_weights": {"gdp_growth": 5.0},
        }
        merged = merge_with_defaults(partial)
        # gdp_growth overridden, others remain 1.0
        assert merged["country_macro_indicator_weights"]["gdp_growth"] == 5.0
        assert merged["country_macro_indicator_weights"]["inflation"] == 1.0
