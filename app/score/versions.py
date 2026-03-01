"""Scoring version constants, weights, and absolute-scoring thresholds."""

COUNTRY_CALC_VERSION = "country_v2"
COUNTRY_SUMMARY_VERSION = "country_summary_v2"

INDUSTRY_CALC_VERSION = "industry_v2"
INDUSTRY_SUMMARY_VERSION = "industry_summary_v2"

COUNTRY_WEIGHTS = {
    "macro": 0.50,
    "market": 0.40,
    "stability": 0.10,
}

COMPANY_CALC_VERSION = "company_v2"
COMPANY_SUMMARY_VERSION = "company_summary_v2"

COMPANY_WEIGHTS = {
    "fundamental": 0.50,
    "market": 0.30,
    "industry_context": 0.20,
}

COMPANY_WEIGHTS_NO_FUNDAMENTALS = {
    "fundamental": 0.0,
    "market": 0.60,
    "industry_context": 0.40,
}

# Recommendation constants
RECOMMENDATION_VERSION = "recommendation_v1"
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
