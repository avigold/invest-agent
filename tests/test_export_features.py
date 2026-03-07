"""Tests for app.export.features — ratio computation, Piotroski, forward returns."""
import math
from datetime import date

import pytest

from app.export.features import (
    compute_derived_ratios,
    compute_forward_returns,
    compute_piotroski_f_score,
    compute_trailing_price_features,
    extract_all_features,
    extract_raw_financials,
)


# ── Fixtures ─────────────────────────────────────────────────────────

def _income(
    revenue=1000, cost_of_revenue=400, gross_profit=600,
    operating_income=300, net_income=200, ebitda=350, ebit=300,
    income_before_tax=280, income_tax_expense=80,
    interest_expense=20, depreciation=50, rd=100,
    eps=2.0, eps_diluted=2.0,
    weighted_avg_shares=100, weighted_avg_shares_dil=100,
    **overrides,
):
    base = {
        "date": "2023-12-31", "symbol": "TEST", "reportedCurrency": "USD",
        "fiscalYear": "2023", "period": "FY",
        "revenue": revenue, "costOfRevenue": cost_of_revenue,
        "grossProfit": gross_profit, "operatingIncome": operating_income,
        "netIncome": net_income, "ebitda": ebitda, "ebit": ebit,
        "incomeBeforeTax": income_before_tax, "incomeTaxExpense": income_tax_expense,
        "interestExpense": interest_expense,
        "depreciationAndAmortization": depreciation,
        "researchAndDevelopmentExpenses": rd,
        "eps": eps, "epsDiluted": eps_diluted,
        "weightedAverageShsOut": weighted_avg_shares,
        "weightedAverageShsOutDil": weighted_avg_shares_dil,
        "sellingGeneralAndAdministrativeExpenses": 100,
        "operatingExpenses": 200,
    }
    base.update(overrides)
    return base


def _balance(
    total_assets=2000, total_liabilities=800,
    equity=1200, current_assets=500, current_liabilities=300,
    cash=200, total_debt=400, net_debt=200,
    inventory=50, receivables=100, long_term_debt=300,
    **overrides,
):
    base = {
        "date": "2023-12-31", "symbol": "TEST", "reportedCurrency": "USD",
        "fiscalYear": "2023", "period": "FY",
        "totalAssets": total_assets, "totalLiabilities": total_liabilities,
        "totalStockholdersEquity": equity,
        "totalCurrentAssets": current_assets,
        "totalCurrentLiabilities": current_liabilities,
        "cashAndCashEquivalents": cash,
        "totalDebt": total_debt, "netDebt": net_debt,
        "inventory": inventory, "netReceivables": receivables,
        "longTermDebt": long_term_debt,
        "goodwill": 0, "intangibleAssets": 0,
    }
    base.update(overrides)
    return base


def _cashflow(
    ocf=250, capex=-80, fcf=170, sbc=30,
    buybacks=0, dividends=0,
    **overrides,
):
    base = {
        "date": "2023-12-31", "symbol": "TEST", "reportedCurrency": "USD",
        "fiscalYear": "2023", "period": "FY",
        "operatingCashFlow": ocf,
        "capitalExpenditure": capex,
        "freeCashFlow": fcf,
        "stockBasedCompensation": sbc,
        "commonStockRepurchased": buybacks,
        "netDividendsPaid": dividends,
        "netIncome": 200,
        "depreciationAndAmortization": 50,
        "changeInWorkingCapital": -20,
    }
    base.update(overrides)
    return base


def _prices(days=500, base_price=100.0, daily_return=0.0003):
    """Generate synthetic daily price data."""
    prices = []
    price = base_price
    d = date(2020, 1, 2)
    for i in range(days):
        prices.append({
            "date": str(d),
            "price": round(price, 2),
            "volume": 1_000_000 + i * 1000,
        })
        price *= (1 + daily_return)
        d = date.fromordinal(d.toordinal() + 1)
        # Skip weekends
        while d.weekday() >= 5:
            d = date.fromordinal(d.toordinal() + 1)
    return prices


# ── Raw financials ───────────────────────────────────────────────────

class TestExtractRawFinancials:
    def test_extracts_income_fields(self):
        result = extract_raw_financials(_income(), None, None)
        assert result["inc_revenue"] == 1000
        assert result["inc_netIncome"] == 200
        assert result["inc_epsDiluted"] == 2.0

    def test_extracts_balance_fields(self):
        result = extract_raw_financials(None, _balance(), None)
        assert result["bal_totalAssets"] == 2000
        assert result["bal_totalDebt"] == 400

    def test_extracts_cashflow_fields(self):
        result = extract_raw_financials(None, None, _cashflow())
        assert result["cf_operatingCashFlow"] == 250
        assert result["cf_freeCashFlow"] == 170

    def test_handles_none_statements(self):
        result = extract_raw_financials(None, None, None)
        assert result == {}

    def test_handles_missing_fields(self):
        inc = {"revenue": 100}  # minimal
        result = extract_raw_financials(inc, None, None)
        assert result["inc_revenue"] == 100
        assert result["inc_netIncome"] is None


# ── Derived ratios ──────────────────────────────────────────────────

class TestComputeDerivedRatios:
    def test_profitability_ratios(self):
        ratios = compute_derived_ratios(_income(), _balance(), _cashflow())
        assert ratios["gross_margin"] == pytest.approx(0.6, abs=0.01)
        assert ratios["operating_margin"] == pytest.approx(0.3, abs=0.01)
        assert ratios["net_margin"] == pytest.approx(0.2, abs=0.01)
        assert ratios["ebitda_margin"] == pytest.approx(0.35, abs=0.01)
        assert ratios["roe"] == pytest.approx(200 / 1200, abs=0.01)
        assert ratios["roa"] == pytest.approx(200 / 2000, abs=0.01)

    def test_leverage_ratios(self):
        ratios = compute_derived_ratios(_income(), _balance(), _cashflow())
        assert ratios["debt_equity"] == pytest.approx(800 / 1200, abs=0.01)
        assert ratios["current_ratio"] == pytest.approx(500 / 300, abs=0.01)
        assert ratios["interest_coverage"] == pytest.approx(300 / 20, abs=0.1)
        assert ratios["cash_ratio"] == pytest.approx(200 / 300, abs=0.01)

    def test_efficiency_ratios(self):
        ratios = compute_derived_ratios(_income(), _balance(), _cashflow())
        assert ratios["asset_turnover"] == pytest.approx(1000 / 2000, abs=0.01)
        assert ratios["receivables_turnover"] == pytest.approx(1000 / 100, abs=0.1)
        assert ratios["inventory_turnover"] == pytest.approx(400 / 50, abs=0.1)

    def test_quality_ratios(self):
        ratios = compute_derived_ratios(_income(), _balance(), _cashflow())
        assert ratios["accruals_ratio"] == pytest.approx((200 - 250) / 2000, abs=0.01)
        assert ratios["sbc_to_revenue"] == pytest.approx(30 / 1000, abs=0.01)
        assert ratios["earnings_quality"] == pytest.approx(250 / 200, abs=0.01)

    def test_growth_with_prior(self):
        prior = _income(revenue=800, net_income=150, epsDiluted=1.5, fiscalYear="2022")
        ratios = compute_derived_ratios(
            _income(), _balance(), _cashflow(),
            prior_income=prior,
        )
        assert ratios["revenue_growth"] == pytest.approx(0.25, abs=0.01)
        assert ratios["net_income_growth"] == pytest.approx(1 / 3, abs=0.01)
        assert ratios["eps_growth"] == pytest.approx(1 / 3, abs=0.01)

    def test_growth_without_prior(self):
        ratios = compute_derived_ratios(_income(), _balance(), _cashflow())
        assert ratios["revenue_growth"] is None
        assert ratios["eps_growth"] is None

    def test_handles_zero_denominators(self):
        ratios = compute_derived_ratios(
            _income(revenue=0),
            _balance(equity=0),
            _cashflow(),
        )
        assert ratios["gross_margin"] is None
        assert ratios["roe"] is None
        assert ratios["net_margin"] is None

    def test_handles_all_none(self):
        ratios = compute_derived_ratios(None, None, None)
        assert ratios["gross_margin"] is None
        assert ratios["roe"] is None
        assert ratios["current_ratio"] is None


# ── Piotroski F-Score ───────────────────────────────────────────────

class TestPiotroskiFScore:
    def test_perfect_score(self):
        """A company that passes all 9 tests."""
        inc = _income(net_income=200)
        bal = _balance(long_term_debt=200, totalCurrentAssets=600, totalCurrentLiabilities=300)
        cf = _cashflow(ocf=300)  # > net_income

        prior_inc = _income(
            net_income=150, revenue=900, grossProfit=500,
            weightedAverageShsOutDil=110,  # more shares = dilution
            fiscalYear="2022",
        )
        prior_bal = _balance(
            long_term_debt=300,  # higher debt in prior year
            totalCurrentAssets=450,
            totalCurrentLiabilities=350,
            totalAssets=1900,
        )
        prior_cf = _cashflow(ocf=180)

        score = compute_piotroski_f_score(inc, bal, cf, prior_inc, prior_bal, prior_cf)
        assert score == 9

    def test_zero_score(self):
        """A company that fails all tests."""
        inc = _income(
            net_income=-100, revenue=800, grossProfit=300,
            weightedAverageShsOutDil=200,
        )
        bal = _balance(
            long_term_debt=500,
            totalCurrentAssets=200,
            totalCurrentLiabilities=400,
            totalAssets=2000,
        )
        # OCF must be <= NI to fail signal #4 (accruals).
        # NI=-100, so OCF must be <= -100.
        cf = _cashflow(ocf=-150)

        prior_inc = _income(
            net_income=-50, revenue=900, grossProfit=400,
            weightedAverageShsOutDil=100,
            fiscalYear="2022",
        )
        prior_bal = _balance(
            long_term_debt=400,
            totalCurrentAssets=300,
            totalCurrentLiabilities=300,
            totalAssets=1800,
        )
        prior_cf = _cashflow(ocf=-30)

        score = compute_piotroski_f_score(inc, bal, cf, prior_inc, prior_bal, prior_cf)
        assert score == 0

    def test_returns_none_without_data(self):
        assert compute_piotroski_f_score(None, None, None, None, None, None) is None

    def test_partial_data(self):
        """Score computable even without prior data (just lower score)."""
        inc = _income(net_income=200)
        bal = _balance()
        cf = _cashflow(ocf=300)
        score = compute_piotroski_f_score(inc, bal, cf, None, None, None)
        assert isinstance(score, int)
        assert 0 <= score <= 9


# ── Price features ──────────────────────────────────────────────────

class TestTrailingPriceFeatures:
    def test_basic_features(self):
        prices = _prices(days=500)
        as_of = date.fromisoformat(prices[-1]["date"])
        result = compute_trailing_price_features(prices, as_of)

        assert "momentum_12m" in result
        assert "volatility_12m" in result
        assert "avg_daily_volume_30d" in result
        assert "distance_from_52w_high" in result

    def test_volume_features(self):
        prices = _prices(days=200)
        as_of = date.fromisoformat(prices[-1]["date"])
        result = compute_trailing_price_features(prices, as_of)

        assert result["avg_daily_volume_30d"] is not None
        assert result["avg_daily_volume_30d"] > 0
        assert result["volume_trend"] is not None

    def test_insufficient_data(self):
        prices = _prices(days=5)
        as_of = date.fromisoformat(prices[-1]["date"])
        result = compute_trailing_price_features(prices, as_of)
        assert result.get("momentum_12m") is None

    def test_empty_prices(self):
        result = compute_trailing_price_features([], date(2023, 12, 31))
        assert result == {}


# ── Forward returns ─────────────────────────────────────────────────

class TestForwardReturns:
    def test_forward_returns_computed(self):
        prices = _prices(days=600, base_price=100)
        as_of = date.fromisoformat(prices[0]["date"])
        result = compute_forward_returns(prices, as_of)

        assert result["fwd_return_3m"] is not None
        assert result["fwd_return_6m"] is not None
        assert result["fwd_return_12m"] is not None

    def test_forward_label_winner(self):
        # Create prices that double in 12 months
        prices = []
        d = date(2020, 1, 2)
        for i in range(600):
            price = 100 * (1 + i * 0.01)  # rapid growth
            prices.append({"date": str(d), "price": price, "volume": 1000})
            d = date.fromordinal(d.toordinal() + 1)
            while d.weekday() >= 5:
                d = date.fromordinal(d.toordinal() + 1)

        result = compute_forward_returns(prices, date(2020, 1, 2))
        assert result["fwd_label"] == "winner"

    def test_forward_label_normal(self):
        prices = _prices(days=600, daily_return=0.0001)  # modest growth
        as_of = date.fromisoformat(prices[0]["date"])
        result = compute_forward_returns(prices, as_of)
        assert result["fwd_label"] == "normal"

    def test_insufficient_future(self):
        prices = _prices(days=30)
        as_of = date.fromisoformat(prices[0]["date"])
        result = compute_forward_returns(prices, as_of)
        assert result["fwd_return_12m"] is None
        assert result["fwd_label"] is None

    def test_max_drawdown(self):
        prices = _prices(days=400, daily_return=-0.001)  # declining
        as_of = date.fromisoformat(prices[0]["date"])
        result = compute_forward_returns(prices, as_of)
        assert result["fwd_max_dd_12m"] is not None
        assert result["fwd_max_dd_12m"] < 0


# ── Integration ─────────────────────────────────────────────────────

class TestExtractAllFeatures:
    def test_produces_rows_per_fiscal_year(self):
        income = [
            _income(fiscalYear="2023"),
            _income(revenue=800, fiscalYear="2022"),
        ]
        balance = [_balance(fiscalYear="2023"), _balance(fiscalYear="2022")]
        cashflow = [_cashflow(fiscalYear="2023"), _cashflow(fiscalYear="2022")]

        rows = extract_all_features(income, balance, cashflow, prices=[])
        assert len(rows) == 2
        assert rows[0]["fiscal_year"] == 2023
        assert rows[1]["fiscal_year"] == 2022

    def test_includes_raw_and_derived(self):
        income = [_income(fiscalYear="2023")]
        balance = [_balance(fiscalYear="2023")]
        cashflow = [_cashflow(fiscalYear="2023")]

        rows = extract_all_features(income, balance, cashflow, prices=[])
        row = rows[0]

        # Raw fields
        assert "inc_revenue" in row
        assert "bal_totalAssets" in row
        assert "cf_freeCashFlow" in row

        # Derived ratios
        assert "gross_margin" in row
        assert "roe" in row
        assert "current_ratio" in row

        # Piotroski
        assert "piotroski_f_score" in row

    def test_growth_computed_from_prior_year(self):
        income = [
            _income(revenue=1200, fiscalYear="2023"),
            _income(revenue=1000, fiscalYear="2022"),
        ]
        balance = [_balance(fiscalYear="2023"), _balance(fiscalYear="2022")]
        cashflow = [_cashflow(fiscalYear="2023"), _cashflow(fiscalYear="2022")]

        rows = extract_all_features(income, balance, cashflow, prices=[])
        row_2023 = rows[0]
        assert row_2023["revenue_growth"] == pytest.approx(0.2, abs=0.01)

    def test_with_prices(self):
        income = [_income(fiscalYear="2021")]
        balance = [_balance(fiscalYear="2021")]
        cashflow = [_cashflow(fiscalYear="2021")]
        prices = _prices(days=800, base_price=50)

        rows = extract_all_features(income, balance, cashflow, prices=prices)
        row = rows[0]
        assert "momentum_12m" in row
        assert "fwd_return_12m" in row

    def test_empty_statements(self):
        rows = extract_all_features([], [], [], prices=[])
        assert rows == []

    def test_context_features_included(self):
        income = [_income(fiscalYear="2023")]
        balance = [_balance(fiscalYear="2023")]
        cashflow = [_cashflow(fiscalYear="2023")]

        rows = extract_all_features(
            income, balance, cashflow, prices=[],
            context={"country_score": 65.2, "company_overall_score": 72.1},
        )
        row = rows[0]
        assert row["ctx_country_score"] == 65.2
        assert row["ctx_company_overall_score"] == 72.1
