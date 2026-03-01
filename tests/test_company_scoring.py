"""Tests for company scoring — EDGAR extraction, derived ratios, subscores, risk detection."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.ingest.sec_edgar import extract_annual_facts
from app.score.company import (
    _compute_derived_ratios,
    _compute_fundamental_subscores,
    detect_company_risks,
)


# ---------------------------------------------------------------------------
# EDGAR fact extraction
# ---------------------------------------------------------------------------

def _make_facts(concept: str, items: list[dict], unit: str = "USD") -> dict:
    """Build a minimal EDGAR facts structure."""
    return {
        "facts": {
            "us-gaap": {
                concept: {
                    "units": {unit: items},
                }
            }
        }
    }


class TestExtractAnnualFacts:
    def test_basic_extraction(self):
        items = [
            {"val": 100_000, "fy": 2023, "form": "10-K", "filed": "2024-02-15", "accn": "a1"},
            {"val": 90_000, "fy": 2022, "form": "10-K", "filed": "2023-02-14", "accn": "a2"},
        ]
        facts = _make_facts("Revenues", items)
        result = extract_annual_facts(facts, ["Revenues"])
        assert len(result) == 2
        assert result[0]["fiscal_year"] == 2023
        assert result[0]["value"] == 100_000
        assert result[1]["fiscal_year"] == 2022

    def test_fallback_concept(self):
        """Should try second concept when first is missing."""
        items = [
            {"val": 50_000, "fy": 2023, "form": "10-K", "filed": "2024-02-15"},
        ]
        facts = _make_facts("RevenueFromContractWithCustomerExcludingAssessedTax", items)
        result = extract_annual_facts(
            facts,
            ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        )
        assert len(result) == 1
        assert result[0]["value"] == 50_000

    def test_filters_10q(self):
        """Should ignore 10-Q forms, only keep 10-K."""
        items = [
            {"val": 100_000, "fy": 2023, "form": "10-K", "filed": "2024-02-15"},
            {"val": 25_000, "fy": 2023, "form": "10-Q", "filed": "2024-05-10"},
        ]
        facts = _make_facts("Revenues", items)
        result = extract_annual_facts(facts, ["Revenues"])
        assert len(result) == 1
        assert result[0]["form"] == "10-K"

    def test_deduplicates_by_fiscal_year(self):
        """Should keep latest filing when multiple 10-K filings for same FY."""
        items = [
            {"val": 100_000, "fy": 2023, "form": "10-K", "filed": "2024-02-15"},
            {"val": 100_500, "fy": 2023, "form": "10-K", "filed": "2024-06-01"},  # amended
        ]
        facts = _make_facts("Revenues", items)
        result = extract_annual_facts(facts, ["Revenues"])
        assert len(result) == 1
        assert result[0]["value"] == 100_500  # keeps later filing

    def test_empty_when_no_concept(self):
        facts = {"facts": {"us-gaap": {}}}
        result = extract_annual_facts(facts, ["Revenues"])
        assert result == []

    def test_empty_when_no_10k(self):
        items = [
            {"val": 25_000, "fy": 2023, "form": "10-Q", "filed": "2024-05-10"},
        ]
        facts = _make_facts("Revenues", items)
        result = extract_annual_facts(facts, ["Revenues"])
        assert result == []

    def test_eps_usd_per_shares_unit(self):
        """EPS uses USD/shares unit key."""
        items = [
            {"val": 6.13, "fy": 2023, "form": "10-K", "filed": "2024-02-02"},
        ]
        facts = _make_facts("EarningsPerShareDiluted", items, unit="USD/shares")
        result = extract_annual_facts(
            facts, ["EarningsPerShareDiluted"], unit_key="USD/shares"
        )
        assert len(result) == 1
        assert result[0]["value"] == pytest.approx(6.13)


# ---------------------------------------------------------------------------
# Derived ratios
# ---------------------------------------------------------------------------

class TestDerivedRatios:
    def test_roe(self):
        fundamentals = {
            "AAPL": {
                "net_income": [100_000.0],
                "stockholders_equity": [50_000.0],
            }
        }
        ratios = _compute_derived_ratios(fundamentals)
        assert ratios["AAPL"]["roe"] == pytest.approx(2.0)

    def test_net_margin(self):
        fundamentals = {
            "AAPL": {
                "net_income": [25_000.0],
                "revenue": [100_000.0],
            }
        }
        ratios = _compute_derived_ratios(fundamentals)
        assert ratios["AAPL"]["net_margin"] == pytest.approx(0.25)

    def test_debt_equity(self):
        fundamentals = {
            "AAPL": {
                "total_liabilities": [200_000.0],
                "stockholders_equity": [100_000.0],
            }
        }
        ratios = _compute_derived_ratios(fundamentals)
        assert ratios["AAPL"]["debt_equity"] == pytest.approx(2.0)

    def test_revenue_growth(self):
        fundamentals = {
            "AAPL": {
                "revenue": [120_000.0, 100_000.0],  # [latest, prior]
            }
        }
        ratios = _compute_derived_ratios(fundamentals)
        assert ratios["AAPL"]["revenue_growth"] == pytest.approx(0.20)

    def test_eps_growth(self):
        fundamentals = {
            "AAPL": {
                "eps_diluted": [6.0, 5.0],
            }
        }
        ratios = _compute_derived_ratios(fundamentals)
        assert ratios["AAPL"]["eps_growth"] == pytest.approx(0.20)

    def test_fcf_yield(self):
        fundamentals = {
            "AAPL": {
                "cash_from_ops": [80_000.0],
                "capex": [20_000.0],
                "revenue": [200_000.0],
            }
        }
        ratios = _compute_derived_ratios(fundamentals)
        # FCF = 80000 - 20000 = 60000; yield = 60000/200000 = 0.30
        assert ratios["AAPL"]["fcf_yield"] == pytest.approx(0.30)

    def test_missing_data_returns_none(self):
        fundamentals = {"AAPL": {}}
        ratios = _compute_derived_ratios(fundamentals)
        assert ratios["AAPL"]["roe"] is None
        assert ratios["AAPL"]["net_margin"] is None
        assert ratios["AAPL"]["debt_equity"] is None
        assert ratios["AAPL"]["revenue_growth"] is None
        assert ratios["AAPL"]["eps_growth"] is None
        assert ratios["AAPL"]["fcf_yield"] is None

    def test_division_by_zero_returns_none(self):
        fundamentals = {
            "AAPL": {
                "net_income": [100_000.0],
                "stockholders_equity": [0.0],
                "revenue": [0.0],
            }
        }
        ratios = _compute_derived_ratios(fundamentals)
        assert ratios["AAPL"]["roe"] is None
        assert ratios["AAPL"]["net_margin"] is None


# ---------------------------------------------------------------------------
# Fundamental sub-scores
# ---------------------------------------------------------------------------

class TestFundamentalSubscores:
    def test_ordering(self):
        """Better ratios should produce higher scores."""
        ratios = {
            "GOOD": {"roe": 0.25, "net_margin": 0.20, "debt_equity": 0.5, "revenue_growth": 0.15, "eps_growth": 0.20, "fcf_yield": 0.15},
            "BAD": {"roe": 0.02, "net_margin": -0.05, "debt_equity": 5.0, "revenue_growth": -0.10, "eps_growth": -0.15, "fcf_yield": -0.05},
            "MID": {"roe": 0.12, "net_margin": 0.08, "debt_equity": 1.5, "revenue_growth": 0.05, "eps_growth": 0.05, "fcf_yield": 0.08},
        }
        scores = _compute_fundamental_subscores(ratios)
        assert scores["GOOD"] > scores["MID"] > scores["BAD"]

    def test_universe_independence(self):
        """Scoring one company gives the same result regardless of universe size."""
        ratios_alone = {
            "A": {"roe": 0.15, "net_margin": 0.10, "debt_equity": 1.0, "revenue_growth": 0.10, "eps_growth": 0.10, "fcf_yield": 0.10},
        }
        ratios_with = {
            "A": {"roe": 0.15, "net_margin": 0.10, "debt_equity": 1.0, "revenue_growth": 0.10, "eps_growth": 0.10, "fcf_yield": 0.10},
            "B": {"roe": 0.30, "net_margin": 0.25, "debt_equity": 0.5, "revenue_growth": 0.30, "eps_growth": 0.40, "fcf_yield": 0.20},
        }
        score_alone = _compute_fundamental_subscores(ratios_alone)
        score_with = _compute_fundamental_subscores(ratios_with)
        assert score_alone["A"] == pytest.approx(score_with["A"])

    def test_determinism(self):
        """Same inputs must produce same outputs."""
        ratios = {
            "A": {"roe": 0.15, "net_margin": 0.10, "debt_equity": 1.0, "revenue_growth": 0.10, "eps_growth": 0.10, "fcf_yield": 0.10},
            "B": {"roe": 0.10, "net_margin": 0.08, "debt_equity": 2.0, "revenue_growth": 0.05, "eps_growth": 0.05, "fcf_yield": 0.05},
        }
        scores1 = _compute_fundamental_subscores(ratios)
        scores2 = _compute_fundamental_subscores(ratios)
        assert scores1 == scores2

    def test_scores_in_range(self):
        """All scores should be 0-100."""
        ratios = {
            "A": {"roe": 0.25, "net_margin": 0.20, "debt_equity": 0.5, "revenue_growth": 0.15, "eps_growth": 0.20, "fcf_yield": 0.15},
            "B": {"roe": 0.02, "net_margin": -0.05, "debt_equity": 5.0, "revenue_growth": -0.10, "eps_growth": -0.15, "fcf_yield": -0.05},
        }
        scores = _compute_fundamental_subscores(ratios)
        for ticker, score in scores.items():
            assert 0 <= score <= 100, f"{ticker} score {score} out of range"


# ---------------------------------------------------------------------------
# Risk detection
# ---------------------------------------------------------------------------

class TestRiskDetection:
    def _make_score(self, overall, ratios=None, market=None):
        score = MagicMock()
        score.overall_score = Decimal(str(overall))
        score.component_data = {
            "fundamental_ratios": ratios or {},
            "market_metrics": market or {},
        }
        return score

    def _make_company(self):
        company = MagicMock()
        company.id = uuid.uuid4()
        company.ticker = "TEST"
        return company

    def test_high_debt_risk(self):
        company = self._make_company()
        score = self._make_score(60.0, ratios={"debt_equity": 4.0})
        logs = []
        risks = detect_company_risks(None, company, score, date(2026, 1, 1), logs.append)
        types = [r.risk_type for r in risks]
        assert "high_debt" in types

    def test_low_margin_risk(self):
        company = self._make_company()
        score = self._make_score(60.0, ratios={"net_margin": -0.05})
        logs = []
        risks = detect_company_risks(None, company, score, date(2026, 1, 1), logs.append)
        types = [r.risk_type for r in risks]
        assert "low_margin" in types

    def test_revenue_decline_risk(self):
        company = self._make_company()
        score = self._make_score(60.0, ratios={"revenue_growth": -0.15})
        logs = []
        risks = detect_company_risks(None, company, score, date(2026, 1, 1), logs.append)
        types = [r.risk_type for r in risks]
        assert "revenue_decline" in types

    def test_market_drawdown_risk(self):
        company = self._make_company()
        score = self._make_score(60.0, market={"max_drawdown": -0.35})
        logs = []
        risks = detect_company_risks(None, company, score, date(2026, 1, 1), logs.append)
        types = [r.risk_type for r in risks]
        assert "market_drawdown" in types

    def test_low_score_risk(self):
        company = self._make_company()
        score = self._make_score(25.0)
        logs = []
        risks = detect_company_risks(None, company, score, date(2026, 1, 1), logs.append)
        types = [r.risk_type for r in risks]
        assert "low_score" in types

    def test_healthy_company_no_risks(self):
        company = self._make_company()
        score = self._make_score(
            70.0,
            ratios={"debt_equity": 1.0, "net_margin": 0.15, "revenue_growth": 0.10},
            market={"max_drawdown": -0.10},
        )
        logs = []
        risks = detect_company_risks(None, company, score, date(2026, 1, 1), logs.append)
        assert len(risks) == 0
