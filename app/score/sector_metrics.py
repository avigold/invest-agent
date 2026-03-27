"""Sector-specific valuation metric definitions.

Each GICS sector gets a curated set of 5–6 multiples that are most
relevant for that sector's valuation. Financials and Real Estate
exclude P/E (distorted by provisions / FFO-based valuation).
"""
from __future__ import annotations

# ── Metric definitions ────────────────────────────────────────────────
# source:
#   "feature"  → read directly from PredictionScore.feature_values[key]
#   "computed"  → needs price + feature_values (P/E, P/B)
# feature_key: override key in feature_values (when different from metric key)

METRIC_DEFINITIONS: dict[str, dict] = {
    "pe_ratio": {
        "label": "P/E Ratio",
        "source": "computed",
        "format": "multiple",
        "higher_is_better": False,
    },
    "pb_ratio": {
        "label": "P/B Ratio",
        "source": "computed",
        "format": "multiple",
        "higher_is_better": False,
    },
    "roe": {
        "label": "ROE",
        "source": "feature",
        "format": "pct",
        "higher_is_better": True,
    },
    "net_margin": {
        "label": "Net Margin",
        "source": "feature",
        "format": "pct",
        "higher_is_better": True,
    },
    "gross_margin": {
        "label": "Gross Margin",
        "source": "feature",
        "format": "pct",
        "higher_is_better": True,
    },
    "operating_margin": {
        "label": "Operating Margin",
        "source": "feature",
        "format": "pct",
        "higher_is_better": True,
    },
    "ebitda_margin": {
        "label": "EBITDA Margin",
        "source": "feature",
        "format": "pct",
        "higher_is_better": True,
    },
    "debt_equity": {
        "label": "Debt / Equity",
        "source": "feature",
        "format": "multiple",
        "higher_is_better": False,
    },
    "fcf_yield": {
        "label": "FCF Yield",
        "source": "feature",
        "format": "pct",
        "higher_is_better": True,
        "feature_key": "fcf_to_net_income",
    },
    "dividend_yield": {
        "label": "Dividend Yield",
        "source": "feature",
        "format": "pct",
        "higher_is_better": True,
        "feature_key": "dividend_payout",
    },
    "revenue_growth": {
        "label": "Revenue Growth",
        "source": "feature",
        "format": "pct",
        "higher_is_better": True,
    },
}

# ── Sector-specific metric lists ──────────────────────────────────────

SECTOR_METRICS: dict[str, list[str]] = {
    "10": ["pe_ratio", "pb_ratio", "fcf_yield", "debt_equity", "roe", "dividend_yield"],
    "15": ["pe_ratio", "pb_ratio", "gross_margin", "roe", "debt_equity", "fcf_yield"],
    "20": ["pe_ratio", "pb_ratio", "operating_margin", "roe", "revenue_growth", "debt_equity"],
    "25": ["pe_ratio", "revenue_growth", "gross_margin", "roe", "fcf_yield", "pb_ratio"],
    "30": ["pe_ratio", "dividend_yield", "gross_margin", "roe", "debt_equity", "pb_ratio"],
    "35": ["pe_ratio", "revenue_growth", "gross_margin", "roe", "fcf_yield", "pb_ratio"],
    "40": ["pb_ratio", "roe", "net_margin", "debt_equity", "dividend_yield"],
    "45": ["pe_ratio", "revenue_growth", "gross_margin", "operating_margin", "roe", "pb_ratio"],
    "50": ["pe_ratio", "revenue_growth", "ebitda_margin", "roe", "fcf_yield", "pb_ratio"],
    "55": ["pe_ratio", "dividend_yield", "debt_equity", "roe", "fcf_yield", "pb_ratio"],
    "60": ["pb_ratio", "dividend_yield", "debt_equity", "roe", "fcf_yield"],
}


def compute_valuation_ratios(
    latest_price: float | None,
    feature_values: dict,
) -> dict[str, float | None]:
    """Compute P/E and P/B from price and feature_values."""
    eps = feature_values.get("inc_epsDiluted")
    net_income = feature_values.get("inc_netIncome")
    book_value = feature_values.get("bal_totalStockholdersEquity")

    pe_ratio: float | None = None
    pb_ratio: float | None = None
    if latest_price and eps and eps > 0:
        pe_ratio = round(latest_price / eps, 1)
    if (
        latest_price
        and eps
        and eps != 0
        and net_income
        and book_value
        and book_value > 0
    ):
        shares = abs(net_income / eps)
        pb_ratio = round((latest_price * shares) / book_value, 1)
    return {"pe_ratio": pe_ratio, "pb_ratio": pb_ratio}


def extract_metric_value(
    metric_key: str,
    feature_values: dict,
    valuation_ratios: dict[str, float | None],
) -> float | None:
    """Extract a metric value from feature_values or computed valuation ratios."""
    defn = METRIC_DEFINITIONS.get(metric_key)
    if not defn:
        return None
    if defn["source"] == "computed":
        return valuation_ratios.get(metric_key)
    # Feature-based: use feature_key override if present, else metric_key
    fv_key = defn.get("feature_key", metric_key)
    val = feature_values.get(fv_key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
