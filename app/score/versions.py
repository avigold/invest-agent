"""Scoring version constants and weights."""

COUNTRY_CALC_VERSION = "country_v1"
COUNTRY_SUMMARY_VERSION = "country_summary_v1"

INDUSTRY_CALC_VERSION = "industry_v1"
INDUSTRY_SUMMARY_VERSION = "industry_summary_v1"

COUNTRY_WEIGHTS = {
    "macro": 0.45,
    "market": 0.35,
    "stability": 0.20,
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
