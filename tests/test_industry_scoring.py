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
    """Energy sector with all favorable conditions should score high."""
    rubric = load_rubric()
    macro = {
        "gdp_growth_pct": 5.0,      # high → favorable; abs_score(5, -2, 8) = 70
        "inflation_pct": 6.0,        # high → favorable; abs_score(6, 1, 15, hib=True) = 35.7
        "current_account_gdp_pct": 3.0,  # high → favorable; abs_score(3, -8, 10) = 61.1
        "stability_index": 0.8,      # high → favorable; abs_score(0.8, 0, 1) = 80
    }
    results = evaluate_rubric(rubric, macro)
    energy = results["energy"]
    assert energy["raw_score"] > 55
    assert energy["max_possible"] == 100
    assert all(s["score"] > 35 for s in energy["signals"])


def test_evaluate_rubric_energy_all_unfavorable():
    """Energy sector with all unfavorable conditions should score low."""
    rubric = load_rubric()
    macro = {
        "gdp_growth_pct": -1.0,     # high favorable; abs_score(-1, -2, 8) = 10
        "inflation_pct": 2.0,        # high favorable; abs_score(2, 1, 15) = 7.1
        "current_account_gdp_pct": -7.0,  # high favorable; abs_score(-7, -8, 10) = 5.6
        "stability_index": 0.1,      # high favorable; abs_score(0.1, 0, 1) = 10
    }
    results = evaluate_rubric(rubric, macro)
    energy = results["energy"]
    assert energy["raw_score"] < 15
    assert all(s["score"] < 15 for s in energy["signals"])


def test_evaluate_rubric_consumer_disc_low_inflation_favorable():
    """Consumer discretionary benefits from LOW inflation."""
    rubric = load_rubric()
    macro = {
        "gdp_growth_pct": 5.0,       # high → favorable
        "unemployment_pct": 3.0,      # low → favorable (hib=False)
        "inflation_pct": 2.0,         # low → favorable (hib=False)
        "central_bank_rate_pct": 2.0, # low → favorable (hib=False)
        "hy_credit_spread_bps": 200,  # low → favorable (hib=False)
    }
    results = evaluate_rubric(rubric, macro)
    cd = results["consumer_discretionary"]
    assert cd["raw_score"] > 55
    assert cd["max_possible"] == 100


def test_evaluate_rubric_missing_data_neutral():
    """Missing indicators should contribute 50 (neutral score)."""
    rubric = load_rubric()
    macro = {
        "gdp_growth_pct": 5.0,      # high → favorable
        # All others missing
    }
    results = evaluate_rubric(rubric, macro)
    energy = results["energy"]
    missing = [s for s in energy["signals"] if s.get("reason") == "missing_data"]
    assert len(missing) == 3
    assert all(s["score"] == 50.0 for s in missing)


def test_evaluate_rubric_financials_yield_curve():
    """Financials benefit from steep yield curve."""
    rubric = load_rubric()
    macro = {
        "yield_curve_10y2y_bps": 150,  # high → favorable; abs_score(150, -100, 300) = 62.5
        "gdp_growth_pct": 4.0,         # high → favorable; abs_score(4, -2, 8) = 60
        "unemployment_pct": 3.0,        # low → favorable; abs_score(3, 2, 15, hib=False) = 92.3
        "hy_credit_spread_bps": 200,    # low → favorable; abs_score(200, 200, 1000, hib=False) = 100
        "stability_index": 0.9,         # high → favorable; abs_score(0.9, 0, 1) = 90
    }
    results = evaluate_rubric(rubric, macro)
    fin = results["financials"]
    assert fin["raw_score"] > 55


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
    score.component_data = {"signals": [{"score": 10}, {"score": 20}]}

    logs: list[str] = []
    risks = detect_industry_risks(industry, country, score, date(2026, 2, 1), logs.append)

    assert len(risks) >= 1
    risk_types = [r.risk_type for r in risks]
    assert "macro_headwinds" in risk_types


def test_detect_risks_all_negative_signals():
    """Should detect all_signals_negative risk when all scores below 30."""
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
            {"score": 10},
            {"score": 15},
            {"score": 25},
        ]
    }

    logs: list[str] = []
    risks = detect_industry_risks(industry, country, score, date(2026, 2, 1), logs.append)

    risk_types = [r.risk_type for r in risks]
    assert "all_signals_negative" in risk_types


def test_detect_risks_no_risks_for_high_score():
    """High-scoring combo with mixed scores should have no risks."""
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
            {"score": 80},
            {"score": 30},
            {"score": 70},
        ]
    }

    logs: list[str] = []
    risks = detect_industry_risks(industry, country, score, date(2026, 2, 1), logs.append)
    assert len(risks) == 0
