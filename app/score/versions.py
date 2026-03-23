"""Scoring version constants, weights, and absolute-scoring thresholds."""

import json
from pathlib import Path

_COUNTRY_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "investable_countries_v1.json"

def _load_allowed_countries() -> list[str]:
    with open(_COUNTRY_CONFIG_PATH) as f:
        data = json.load(f)
    return [c["iso2"] for c in data["countries"]]

ALLOWED_COUNTRIES: list[str] = _load_allowed_countries()

COUNTRY_CALC_VERSION = "country_v2"
COUNTRY_SUMMARY_VERSION = "country_summary_v2"

INDUSTRY_CALC_VERSION = "industry_v3"
INDUSTRY_SUMMARY_VERSION = "industry_summary_v3"

COUNTRY_WEIGHTS = {
    "macro": 0.50,
    "market": 0.40,
    "stability": 0.10,
}

COMPANY_CALC_VERSION = "company_v3"
COMPANY_SUMMARY_VERSION = "company_summary_v3"

COMPANY_WEIGHTS = {
    "fundamental": 0.60,
    "market": 0.40,
}

COMPANY_WEIGHTS_NO_FUNDAMENTALS = {
    "fundamental": 0.0,
    "market": 1.0,
}

# Recommendation constants
RECOMMENDATION_VERSION = "recommendation_v2"
RECOMMENDATION_WEIGHTS = {"country": 0.20, "industry": 0.20, "company": 0.60}
RECOMMENDATION_THRESHOLDS = {"buy": 70, "sell": 40}

# Fundamental indicators: name -> higher_is_better
FUNDAMENTAL_INDICATORS = {
    "roe": True,
    "net_margin": True,
    "debt_equity": False,
    "revenue_growth": True,
    "eps_growth": True,
    "fcf_yield": True,
}

# Macro indicators: series_name -> higher_is_better
MACRO_INDICATORS = {
    "gdp_growth": True,
    "inflation": False,
    "unemployment": False,
    "govt_debt_gdp": False,
    "current_account_gdp": True,
    "fdi_gdp": True,
    "reserves": True,
    "gdp_per_capita": True,
    "market_cap_gdp": True,
    "household_consumption_pc": True,
}

# ---------------------------------------------------------------------------
# Absolute-scoring thresholds  (floor → 0, ceiling → 100)
# ---------------------------------------------------------------------------

# Country macro indicators
# Convention: floor < ceiling (natural order); higher_is_better controls direction.
MACRO_ABSOLUTE_THRESHOLDS: dict[str, dict] = {
    "gdp_growth":         {"floor": -2.0,  "ceiling": 8.0,   "higher_is_better": True},
    "inflation":          {"floor": 1.0,   "ceiling": 15.0,  "higher_is_better": False},
    "unemployment":       {"floor": 2.0,   "ceiling": 15.0,  "higher_is_better": False},
    "govt_debt_gdp":      {"floor": 20.0,  "ceiling": 200.0, "higher_is_better": False},
    "current_account_gdp":{"floor": -8.0,  "ceiling": 10.0,  "higher_is_better": True},
    "fdi_gdp":            {"floor": -1.0,  "ceiling": 8.0,   "higher_is_better": True},
    "reserves":           {"floor": 0.0,   "ceiling": 500_000_000_000, "higher_is_better": True},  # USD (raw)
    "gdp_per_capita":     {"floor": 5_000, "ceiling": 100_000, "higher_is_better": True},  # USD
    "market_cap_gdp":     {"floor": 20.0,  "ceiling": 200.0,   "higher_is_better": True},  # percent of GDP
    "household_consumption_pc": {"floor": 10_000, "ceiling": 45_000, "higher_is_better": True},  # constant 2015 USD
}

# Industry macro sensitivity indicators (floor/ceiling only — direction comes from rubric config)
INDUSTRY_INDICATOR_THRESHOLDS: dict[str, dict] = {
    "gdp_growth":         {"floor": -2.0,  "ceiling": 8.0},
    "inflation":          {"floor": 1.0,   "ceiling": 15.0},
    "unemployment":       {"floor": 2.0,   "ceiling": 15.0},
    "govt_debt_gdp":      {"floor": 20.0,  "ceiling": 200.0},
    "current_account_gdp":{"floor": -8.0,  "ceiling": 10.0},
    "fdi_gdp":            {"floor": -1.0,  "ceiling": 8.0},
    "fedfunds":           {"floor": 0.0,   "ceiling": 10.0},
    "hy_spread":          {"floor": 200.0, "ceiling": 1000.0},
    "yield_curve":        {"floor": -100.0,"ceiling": 300.0},
    "stability":          {"floor": 0.0,   "ceiling": 1.0},
}

# Market metrics (shared by country and company)
MARKET_ABSOLUTE_THRESHOLDS: dict[str, dict] = {
    "return_1y":     {"floor": -0.40, "ceiling": 0.40, "higher_is_better": True},
    "max_drawdown":  {"floor": -0.50, "ceiling": 0.00, "higher_is_better": True},
    "ma_spread":     {"floor": -0.20, "ceiling": 0.20, "higher_is_better": True},
}

# Company fundamental ratios
# Convention: floor < ceiling (natural order); higher_is_better controls direction.
FUNDAMENTAL_ABSOLUTE_THRESHOLDS: dict[str, dict] = {
    "roe":            {"floor": -0.20, "ceiling": 0.30, "higher_is_better": True},
    "net_margin":     {"floor": -0.15, "ceiling": 0.25, "higher_is_better": True},
    "debt_equity":    {"floor": 0.0,   "ceiling": 5.0,  "higher_is_better": False},
    "revenue_growth": {"floor": -0.20, "ceiling": 0.30, "higher_is_better": True},
    "eps_growth":     {"floor": -0.30, "ceiling": 0.50, "higher_is_better": True},
    "fcf_yield":      {"floor": -0.10, "ceiling": 0.20, "higher_is_better": True},
}
