"""Live screener: filter the current company universe on financial metrics.

Pure functions — no DB access, no API calls. Takes enriched row dicts
and applies user-defined filter rules.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from app.score.feature_scorer import score_from_features


# ── Field definitions ────────────────────────────────────────────────────

FieldDef = dict[str, Any]

FIELD_DEFINITIONS: list[FieldDef] = [
    # Descriptive
    {"key": "country", "label": "Country", "type": "categorical", "category": "Descriptive"},
    {"key": "sector", "label": "Sector", "type": "categorical", "category": "Descriptive"},
    {"key": "ml_classification", "label": "ML Classification", "type": "categorical", "category": "Descriptive",
     "values": ["high", "medium", "low", "negligible"]},
    {"key": "det_classification", "label": "Deterministic Classification", "type": "categorical", "category": "Descriptive",
     "values": ["Buy", "Hold", "Sell"]},

    # Valuation
    {"key": "pe_ratio", "label": "P/E Ratio", "type": "numeric", "category": "Valuation", "format": "x"},
    {"key": "pb_ratio", "label": "P/B Ratio", "type": "numeric", "category": "Valuation", "format": "x"},

    # Profitability
    {"key": "roe", "label": "ROE", "type": "numeric", "category": "Profitability", "format": "percent"},
    {"key": "roa", "label": "ROA", "type": "numeric", "category": "Profitability", "format": "percent"},
    {"key": "net_margin", "label": "Net Margin", "type": "numeric", "category": "Profitability", "format": "percent"},
    {"key": "gross_margin", "label": "Gross Margin", "type": "numeric", "category": "Profitability", "format": "percent"},
    {"key": "operating_margin", "label": "Operating Margin", "type": "numeric", "category": "Profitability", "format": "percent"},

    # Growth
    {"key": "revenue_growth", "label": "Revenue Growth", "type": "numeric", "category": "Growth", "format": "percent"},
    {"key": "eps_growth", "label": "EPS Growth", "type": "numeric", "category": "Growth", "format": "percent"},

    # Financial Health
    {"key": "debt_equity", "label": "Debt / Equity", "type": "numeric", "category": "Financial Health", "format": "x"},
    {"key": "current_ratio", "label": "Current Ratio", "type": "numeric", "category": "Financial Health", "format": "x"},
    {"key": "interest_coverage", "label": "Interest Coverage", "type": "numeric", "category": "Financial Health", "format": "x"},

    # Income
    {"key": "dividend_yield", "label": "Dividend Yield", "type": "numeric", "category": "Income", "format": "percent"},
    {"key": "fcf_yield", "label": "FCF Yield", "type": "numeric", "category": "Income", "format": "percent"},

    # ML Signals
    {"key": "probability", "label": "ML Probability", "type": "numeric", "category": "ML Signals", "format": "decimal"},
    {"key": "fundamental_score", "label": "Fundamental Score", "type": "numeric", "category": "ML Signals", "format": "score"},
    {"key": "market_score", "label": "Market Score", "type": "numeric", "category": "ML Signals", "format": "score"},
    {"key": "company_score", "label": "Company Score", "type": "numeric", "category": "ML Signals", "format": "score"},

    # Performance
    {"key": "momentum_12m", "label": "Momentum 12M", "type": "numeric", "category": "Performance", "format": "percent"},
    {"key": "max_dd_12m", "label": "Max Drawdown 12M", "type": "numeric", "category": "Performance", "format": "percent"},
]

_FIELD_MAP: dict[str, FieldDef] = {f["key"]: f for f in FIELD_DEFINITIONS}


# ── Pre-built templates ──────────────────────────────────────────────────

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "tpl_value",
        "name": "Value",
        "description": "Low-valuation companies with manageable debt",
        "is_template": True,
        "filters": {"rules": [
            {"field": "pe_ratio", "op": "lt", "value": 15},
            {"field": "pb_ratio", "op": "lt", "value": 2},
            {"field": "debt_equity", "op": "lt", "value": 2},
        ]},
    },
    {
        "id": "tpl_growth",
        "name": "Growth",
        "description": "High revenue and earnings growth with positive momentum",
        "is_template": True,
        "filters": {"rules": [
            {"field": "revenue_growth", "op": "gt", "value": 0.15},
            {"field": "eps_growth", "op": "gt", "value": 0.15},
            {"field": "momentum_12m", "op": "gt", "value": 0.10},
        ]},
    },
    {
        "id": "tpl_dividend",
        "name": "Dividend",
        "description": "Income-generating companies with solid cash flow",
        "is_template": True,
        "filters": {"rules": [
            {"field": "dividend_yield", "op": "gt", "value": 0.02},
            {"field": "fcf_yield", "op": "gt", "value": 0.05},
            {"field": "debt_equity", "op": "lt", "value": 3},
        ]},
    },
    {
        "id": "tpl_quality",
        "name": "Quality",
        "description": "Highly profitable companies with strong balance sheets",
        "is_template": True,
        "filters": {"rules": [
            {"field": "roe", "op": "gt", "value": 0.15},
            {"field": "net_margin", "op": "gt", "value": 0.10},
            {"field": "current_ratio", "op": "gt", "value": 1.5},
            {"field": "debt_equity", "op": "lt", "value": 1.5},
        ]},
    },
    {
        "id": "tpl_momentum",
        "name": "Momentum",
        "description": "Strong recent performance with limited drawdown",
        "is_template": True,
        "filters": {"rules": [
            {"field": "momentum_12m", "op": "gt", "value": 0.20},
            {"field": "max_dd_12m", "op": "gt", "value": -0.20},
        ]},
    },
    {
        "id": "tpl_ml_conviction",
        "name": "ML High Conviction",
        "description": "Stocks with the highest ML model confidence",
        "is_template": True,
        "filters": {"rules": [
            {"field": "probability", "op": "gt", "value": 0.7},
        ]},
    },
]


# ── Enriched row builder ─────────────────────────────────────────────────

def build_enriched_row(
    score_row,
    latest_price: float | None = None,
) -> dict[str, Any]:
    """Flatten a PredictionScore row into a screenable dict.

    ``score_row`` must have attributes: ticker, company_name, country,
    sector, probability, confidence_tier, kelly_fraction, suggested_weight,
    feature_values, scored_at.
    """
    fv: dict = score_row.feature_values or {}

    # Deterministic scores
    det = score_from_features(fv)

    # Derived valuation ratios
    eps = fv.get("inc_epsDiluted")
    net_income = fv.get("inc_netIncome")
    book_value = fv.get("bal_totalStockholdersEquity")

    pe_ratio: float | None = None
    pb_ratio: float | None = None
    market_cap: int | None = None
    if latest_price and eps and eps > 0:
        pe_ratio = round(latest_price / eps, 1)
    if latest_price and eps and eps != 0 and net_income and book_value and book_value > 0:
        shares = abs(net_income / eps)
        market_cap = int(latest_price * shares)
        pb_ratio = round((latest_price * shares) / book_value, 1)

    return {
        "ticker": score_row.ticker,
        "company_name": score_row.company_name,
        "country": score_row.country or "",
        "sector": score_row.sector or "",

        # ML signals
        "probability": score_row.probability,
        "ml_classification": score_row.confidence_tier,
        "kelly_fraction": score_row.kelly_fraction,
        "suggested_weight": score_row.suggested_weight,

        # Valuation
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "market_cap": market_cap,

        # Profitability
        "roe": fv.get("roe"),
        "roa": fv.get("roa"),
        "net_margin": fv.get("net_margin"),
        "gross_margin": fv.get("gross_margin"),
        "operating_margin": fv.get("operating_margin"),

        # Growth
        "revenue_growth": fv.get("revenue_growth"),
        "eps_growth": fv.get("eps_growth"),

        # Financial health
        "debt_equity": fv.get("debt_equity"),
        "current_ratio": fv.get("current_ratio"),
        "interest_coverage": fv.get("interest_coverage"),

        # Income
        "fcf_yield": fv.get("fcf_yield") or fv.get("fcf_to_net_income"),
        "dividend_yield": fv.get("dividend_payout"),

        # Performance
        "momentum_12m": fv.get("momentum_12m"),
        "max_dd_12m": fv.get("max_dd_12m"),

        # Deterministic scores
        "fundamental_score": det["fundamental_score"],
        "market_score": det["market_score"],
        "company_score": det["company_score"],
        "det_classification": det["classification"],
    }


# ── Filter engine ────────────────────────────────────────────────────────

def _apply_rule(row: dict[str, Any], rule: dict) -> bool:
    """Apply a single filter rule. Returns True if row passes."""
    field = rule.get("field", "")
    op = rule.get("op", "")
    value = rule.get("value")

    row_val = row.get(field)

    # Null values never pass numeric comparisons
    if row_val is None:
        return False

    if op == "gt":
        return float(row_val) > float(value)
    if op == "gte":
        return float(row_val) >= float(value)
    if op == "lt":
        return float(row_val) < float(value)
    if op == "lte":
        return float(row_val) <= float(value)
    if op == "eq":
        return str(row_val) == str(value)
    if op == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return False
        v = float(row_val)
        return float(value[0]) <= v <= float(value[1])
    if op == "in":
        if not isinstance(value, (list, tuple)):
            return False
        return str(row_val) in [str(v) for v in value]
    if op == "not_in":
        if not isinstance(value, (list, tuple)):
            return True
        return str(row_val) not in [str(v) for v in value]

    return True  # Unknown operator — pass through


def apply_filters(
    rows: list[dict[str, Any]], rules: list[dict]
) -> list[dict[str, Any]]:
    """Apply all filter rules (AND logic). Returns matching rows."""
    if not rules:
        return rows
    return [row for row in rows if all(_apply_rule(row, r) for r in rules)]


# ── CSV export helper ────────────────────────────────────────────────────

DEFAULT_COLUMNS = [
    "ticker", "company_name", "country", "sector",
    "pe_ratio", "pb_ratio", "roe", "net_margin", "revenue_growth",
    "probability", "det_classification",
]


def rows_to_csv(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    """Serialise rows to CSV string."""
    cols = columns or DEFAULT_COLUMNS
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in cols})
    return buf.getvalue()
