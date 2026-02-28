"""Tests for industry scoring engine — rubric evaluation, percentile ranking, risk detection."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.score.industry import evaluate_rubric, load_rubric, detect_industry_risks


# ---------------------------------------------------------------------------
# Rubric loading
# ---------------------------------------------------------------------------

def test_load_rubric_has_11_sectors():
    rubric = load_rubric()
    assert len(rubric["sectors"]) == 11
    # Verify all GICS codes present
    codes = {s["gics_code"] for s in rubric["sectors"].values()}
    assert codes == {"10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60"}


def test_load_rubric_has_thresholds():
    rubric = load_rubric()
    assert "gdp_growth_pct" in rubric["thresholds"]
    assert "inflation_pct" in rubric["thresholds"]
    assert rubric["thresholds"]["gdp_growth_pct"]["threshold"] == 3.0


# ---------------------------------------------------------------------------
# Rubric evaluation
# ---------------------------------------------------------------------------

def test_evaluate_rubric_energy_all_favorable():
    """Energy sector with all favorable conditions should get max raw score."""
    rubric = load_rubric()
    macro = {
        "gdp_growth_pct": 5.0,      # high → favorable (threshold 3.0)
        "inflation_pct": 6.0,        # high → favorable (threshold 4.0)
        "current_account_gdp_pct": 3.0,  # high → favorable (threshold 0.0)
        "stability_index": 0.8,      # high → favorable (threshold 0.5)
    }
    results = evaluate_rubric(rubric, macro)
    energy = results["energy"]
    assert energy["raw_score"] == 4  # all 4 signals positive
    assert energy["max_possible"] == 4
    assert all(s["signal"] == 1 for s in energy["signals"])


def test_evaluate_rubric_energy_all_unfavorable():
    """Energy sector with all unfavorable conditions should get min raw score."""
    rubric = load_rubric()
    macro = {
        "gdp_growth_pct": 1.0,      # low → unfavorable
        "inflation_pct": 2.0,        # low → unfavorable
        "current_account_gdp_pct": -2.0,  # low → unfavorable
        "stability_index": 0.3,      # low → unfavorable
    }
    results = evaluate_rubric(rubric, macro)
    energy = results["energy"]
    assert energy["raw_score"] == -4
    assert all(s["signal"] == -1 for s in energy["signals"])


def test_evaluate_rubric_consumer_disc_low_inflation_favorable():
    """Consumer discretionary benefits from LOW inflation."""
    rubric = load_rubric()
    macro = {
        "gdp_growth_pct": 5.0,       # high → favorable
        "unemployment_pct": 3.0,      # low → favorable
        "inflation_pct": 2.0,         # low → favorable
        "central_bank_rate_pct": 2.0, # low → favorable
        "hy_credit_spread_bps": 200,  # low → favorable
    }
    results = evaluate_rubric(rubric, macro)
    cd = results["consumer_discretionary"]
    assert cd["raw_score"] == 5  # all favorable
    assert cd["max_possible"] == 5


def test_evaluate_rubric_missing_data_neutral():
    """Missing indicators should contribute 0 (neutral signal)."""
    rubric = load_rubric()
    macro = {
        "gdp_growth_pct": 5.0,      # high → favorable
        # All others missing
    }
    results = evaluate_rubric(rubric, macro)
    energy = results["energy"]
    # 1 favorable + 3 missing (0)
    assert energy["raw_score"] == 1
    missing = [s for s in energy["signals"] if s.get("reason") == "missing_data"]
    assert len(missing) == 3


def test_evaluate_rubric_financials_yield_curve():
    """Financials benefit from steep yield curve."""
    rubric = load_rubric()
    macro = {
        "yield_curve_10y2y_bps": 150,  # high → favorable (threshold 50)
        "gdp_growth_pct": 4.0,         # high → favorable
        "unemployment_pct": 3.0,        # low → favorable
        "hy_credit_spread_bps": 200,    # low → favorable
        "stability_index": 0.9,         # high → favorable
    }
    results = evaluate_rubric(rubric, macro)
    fin = results["financials"]
    assert fin["raw_score"] == 5  # all 5 favorable


def test_evaluate_rubric_returns_all_sectors():
    """evaluate_rubric should return results for all 11 sectors."""
    rubric = load_rubric()
    macro = {"gdp_growth_pct": 3.0}  # just one indicator
    results = evaluate_rubric(rubric, macro)
    assert len(results) == 11


# ---------------------------------------------------------------------------
# Percentile ranking (reuses country.percentile_rank)
# ---------------------------------------------------------------------------

def test_percentile_rank_basic():
    from app.score.country import percentile_rank
    # 5 values: 1, 2, 3, 4, 5
    ranks = percentile_rank([1.0, 2.0, 3.0, 4.0, 5.0], higher_is_better=True)
    # Highest (5) should be rank 1.0, lowest (1) should be 0.0
    assert ranks[4] == 1.0
    assert ranks[0] == 0.0


def test_percentile_rank_with_ties():
    from app.score.country import percentile_rank
    # Tied values
    ranks = percentile_rank([3.0, 3.0, 1.0], higher_is_better=True)
    # 3,3 should share highest rank
    assert ranks[0] == ranks[1]
    assert ranks[2] == 0.0


# ---------------------------------------------------------------------------
# Risk detection
# ---------------------------------------------------------------------------

def test_detect_risks_low_score():
    """Should detect macro_headwinds risk for low-scoring combo."""
    industry = MagicMock()
    industry.id = uuid.uuid4()
    industry.name = "Energy"

    country = MagicMock()
    country.id = uuid.uuid4()
    country.iso2 = "BR"

    score = MagicMock()
    score.overall_score = Decimal("15.0")
    score.component_data = {"signals": [{"signal": -1}, {"signal": -1}]}

    logs: list[str] = []
    risks = detect_industry_risks(industry, country, score, date(2026, 2, 1), logs.append)

    assert len(risks) >= 1
    risk_types = [r.risk_type for r in risks]
    assert "macro_headwinds" in risk_types


def test_detect_risks_all_negative_signals():
    """Should detect all_signals_negative risk."""
    industry = MagicMock()
    industry.id = uuid.uuid4()
    industry.name = "Utilities"

    country = MagicMock()
    country.id = uuid.uuid4()
    country.iso2 = "BR"

    score = MagicMock()
    score.overall_score = Decimal("35.0")  # above 30, so no headwinds
    score.component_data = {
        "signals": [
            {"signal": -1},
            {"signal": -1},
            {"signal": -1},
        ]
    }

    logs: list[str] = []
    risks = detect_industry_risks(industry, country, score, date(2026, 2, 1), logs.append)

    risk_types = [r.risk_type for r in risks]
    assert "all_signals_negative" in risk_types


def test_detect_risks_no_risks_for_high_score():
    """High-scoring combo with mixed signals should have no risks."""
    industry = MagicMock()
    industry.id = uuid.uuid4()
    industry.name = "IT"

    country = MagicMock()
    country.id = uuid.uuid4()
    country.iso2 = "US"

    score = MagicMock()
    score.overall_score = Decimal("75.0")
    score.component_data = {
        "signals": [
            {"signal": 1},
            {"signal": -1},
            {"signal": 1},
        ]
    }

    logs: list[str] = []
    risks = detect_industry_risks(industry, country, score, date(2026, 2, 1), logs.append)
    assert len(risks) == 0
