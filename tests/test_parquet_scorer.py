"""Tests for app.predict.parquet_scorer — ML scoring from Parquet."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.predict.parquet_scorer import (
    ML_AVG_LOSS,
    ML_AVG_WIN,
    ML_TOP_N,
    ScoredStock,
    _build_portfolio,
    _confidence_tier,
    _gics_to_sector,
    _kelly_fraction,
    score_from_parquet,
)


# ── Fixtures ────────────────────────────────────────────────────────


def _make_parquet(tmp_path: Path, n_tickers: int = 20, n_years: int = 3) -> str:
    """Create a synthetic Parquet file with multiple years per ticker."""
    rng = np.random.RandomState(42)
    rows = []
    for i in range(n_tickers):
        ticker = f"T{i:03d}"
        country = ["US", "GB", "IN", "DE"][i % 4]
        gics = ["45", "20", "35", "40"][i % 4]
        for yr in range(2022, 2022 + n_years):
            rows.append({
                "fiscal_year": yr,
                "statement_date": f"{yr}-12-31",
                "reported_currency": "USD",
                "ticker": ticker,
                "company_name": f"{ticker} Corp",
                "country_iso2": country,
                "gics_code": gics,
                "inc_revenue": float(rng.uniform(100, 10000)),
                "inc_netIncome": float(rng.uniform(-100, 1000)),
                "gross_margin": float(rng.uniform(0.1, 0.9)),
                "roe": float(rng.uniform(-0.5, 1.0)),
                "momentum_12m": float(rng.uniform(-0.5, 2.0)),
                "volatility_12m": float(rng.uniform(0.1, 1.0)),
                "max_dd_12m": float(rng.uniform(-0.8, 0)),
                "dollar_volume_30d": float(rng.uniform(100_000, 10_000_000)),
                "relative_strength_12m": None,
                "beta_vs_index": None,
                "fwd_return_3m": float(rng.uniform(-0.5, 1.0)),
                "fwd_return_6m": float(rng.uniform(-0.5, 2.0)),
                "fwd_return_12m": float(rng.uniform(-0.5, 3.0)),
                "fwd_return_24m": float(rng.uniform(-0.5, 5.0)),
                "fwd_max_dd_12m": float(rng.uniform(-0.8, 0)),
                "fwd_label": rng.choice(["winner", "normal"]),
            })
    table = pa.Table.from_pylist(rows)
    path = str(tmp_path / "test_features.parquet")
    pq.write_table(table, path)
    return path


def _make_mock_model(feature_names: list[str]) -> MagicMock:
    """Create a mock TrainedModel."""
    model = MagicMock()
    model.feature_names = feature_names
    model.feature_importance = {f: 1.0 / len(feature_names) for f in feature_names[:5]}
    # predict_proba returns linearly spaced values
    model.predict_proba = MagicMock(
        side_effect=lambda X: np.linspace(0.05, 0.50, len(X))
    )
    return model


# ── Kelly Fraction Tests ─────────────────────────────────────────


class TestKellyFraction:
    def test_zero_probability(self):
        assert _kelly_fraction(0.0) == 0.0

    def test_high_probability(self):
        k = _kelly_fraction(0.50)
        assert k > 0.0

    def test_low_probability_zero(self):
        # Very low probability shouldn't produce positive Kelly
        k = _kelly_fraction(0.05)
        assert k == 0.0

    def test_uses_relative_params(self):
        # Both should produce positive Kelly fractions
        k_relative = _kelly_fraction(0.40, avg_win=0.42, avg_loss=-0.15)
        k_lottery = _kelly_fraction(0.40, avg_win=3.0, avg_loss=-0.50)
        assert k_relative > 0.0
        assert k_lottery > 0.0
        # They should differ (different economics)
        assert k_relative != k_lottery


# ── Confidence Tier Tests ────────────────────────────────────────


class TestConfidenceTier:
    def test_high(self):
        assert _confidence_tier(0.35) == "high"

    def test_medium(self):
        assert _confidence_tier(0.20) == "medium"

    def test_low(self):
        assert _confidence_tier(0.08) == "low"

    def test_negligible(self):
        assert _confidence_tier(0.02) == "negligible"


# ── GICS Sector Mapping ─────────────────────────────────────────


class TestGicsSector:
    def test_known_code(self):
        assert _gics_to_sector("45") == "Information Technology"
        assert _gics_to_sector("20") == "Industrials"

    def test_longer_code(self):
        assert _gics_to_sector("4510") == "Information Technology"

    def test_empty(self):
        assert _gics_to_sector("") == "Unknown"


# ── Score From Parquet Tests ─────────────────────────────────────


class TestScoreFromParquet:
    def test_deduplicates_to_most_recent_year(self, tmp_path):
        path = _make_parquet(tmp_path, n_tickers=10, n_years=3)
        # Feature names that exist in our synthetic data
        feature_names = [
            "inc_revenue", "inc_netIncome", "gross_margin", "roe",
            "momentum_12m", "volatility_12m", "max_dd_12m", "dollar_volume_30d",
            "cat_gics_code", "cat_country_iso2",
        ]
        model = _make_mock_model(feature_names)

        scored = score_from_parquet(path, model, model_config={})

        # Should have exactly 10 stocks (one per ticker)
        assert len(scored) == 10
        tickers = [s.ticker for s in scored]
        assert len(set(tickers)) == 10

    def test_most_recent_year_selected(self, tmp_path):
        path = _make_parquet(tmp_path, n_tickers=5, n_years=3)
        feature_names = ["inc_revenue", "gross_margin", "cat_gics_code", "cat_country_iso2"]
        model = _make_mock_model(feature_names)

        scored = score_from_parquet(path, model, model_config={})

        # All should be from the latest year (2024)
        for s in scored:
            assert s.fiscal_year == 2024

    def test_sorted_by_probability_desc(self, tmp_path):
        path = _make_parquet(tmp_path, n_tickers=10, n_years=1)
        feature_names = ["inc_revenue", "gross_margin", "cat_gics_code", "cat_country_iso2"]
        model = _make_mock_model(feature_names)

        scored = score_from_parquet(path, model, model_config={})

        probs = [s.probability for s in scored]
        assert probs == sorted(probs, reverse=True)

    def test_country_populated(self, tmp_path):
        path = _make_parquet(tmp_path, n_tickers=8, n_years=1)
        feature_names = ["inc_revenue", "cat_gics_code", "cat_country_iso2"]
        model = _make_mock_model(feature_names)

        scored = score_from_parquet(path, model, model_config={})

        countries = {s.country for s in scored}
        assert len(countries) > 1  # Multiple countries present

    def test_country_filter_from_config(self, tmp_path):
        path = _make_parquet(tmp_path, n_tickers=20, n_years=1)
        feature_names = ["inc_revenue", "cat_gics_code", "cat_country_iso2"]
        model = _make_mock_model(feature_names)

        config = {"allowed_countries": ["US"]}
        scored = score_from_parquet(path, model, model_config=config)

        for s in scored:
            assert s.country == "US"

    def test_deduplicates_by_company_name(self, tmp_path):
        """Duplicate company names (different tickers) should be deduped."""
        rng = np.random.RandomState(99)
        rows = []
        # 3 tickers for the same company + 7 unique companies = 10 tickers
        for i, (ticker, company) in enumerate([
            ("NVDA", "NVIDIA Corporation"),
            ("NVD.DE", "NVIDIA Corporation"),
            ("NVD.F", "NVIDIA Corporation"),
            ("AAPL", "Apple Inc"),
            ("MSFT", "Microsoft Corp"),
            ("GOOG", "Alphabet Inc"),
            ("AMZN", "Amazon Inc"),
            ("META", "Meta Platforms"),
            ("TSLA", "Tesla Inc"),
            ("NFLX", "Netflix Inc"),
        ]):
            rows.append({
                "fiscal_year": 2024, "statement_date": "2024-12-31",
                "reported_currency": "USD", "ticker": ticker,
                "company_name": company,
                "country_iso2": "US", "gics_code": "45",
                "inc_revenue": float(rng.uniform(100, 10000)),
                "inc_netIncome": float(rng.uniform(-100, 1000)),
                "gross_margin": float(rng.uniform(0.1, 0.9)),
                "roe": float(rng.uniform(-0.5, 1.0)),
                "momentum_12m": float(rng.uniform(-0.5, 2.0)),
                "volatility_12m": float(rng.uniform(0.1, 1.0)),
                "max_dd_12m": float(rng.uniform(-0.8, 0)),
                "dollar_volume_30d": float(rng.uniform(100_000, 10_000_000)),
                "relative_strength_12m": None, "beta_vs_index": None,
                "fwd_return_3m": 0.0, "fwd_return_6m": 0.0,
                "fwd_return_12m": 0.5, "fwd_return_24m": 1.0,
                "fwd_max_dd_12m": -0.1, "fwd_label": "winner",
            })
        table = pa.Table.from_pylist(rows)
        path = str(tmp_path / "dup_test.parquet")
        pq.write_table(table, path)

        feature_names = ["inc_revenue", "gross_margin", "cat_gics_code", "cat_country_iso2"]
        model = _make_mock_model(feature_names)

        # With dedup (default)
        scored = score_from_parquet(path, model, model_config={})
        company_names = [s.company_name for s in scored]
        assert len(company_names) == 8  # 10 tickers - 2 NVIDIA dupes
        assert company_names.count("NVIDIA Corporation") == 1

        # Without dedup
        scored_all = score_from_parquet(path, model, model_config={}, deduplicate=False)
        assert len(scored_all) == 10

    def test_feature_alignment(self, tmp_path):
        path = _make_parquet(tmp_path, n_tickers=5, n_years=1)
        # Include a feature that doesn't exist in Parquet
        feature_names = ["inc_revenue", "gross_margin", "nonexistent_feature",
                         "cat_gics_code", "cat_country_iso2"]
        model = _make_mock_model(feature_names)

        logs = []
        scored = score_from_parquet(path, model, model_config={}, log_fn=logs.append)

        # Should still produce scores (NaN for missing features)
        assert len(scored) == 5
        # Feature alignment log should show partial match
        alignment_logs = [l for l in logs if "Feature alignment" in l]
        assert len(alignment_logs) == 1
        # 4 out of 5 should match (nonexistent_feature won't)
        assert "4/5" in alignment_logs[0]


# ── Portfolio Construction Tests ─────────────────────────────────


class TestBuildPortfolio:
    """Tests for top-50 equal-weight portfolio (validated methodology)."""

    def _make_scored(self, n: int, probability: float = 0.35,
                     country: str = "US", sector: str = "Tech") -> list[ScoredStock]:
        return [
            ScoredStock(
                ticker=f"T{i}",
                company_name=f"T{i} Corp",
                country=country,
                sector=sector,
                fiscal_year=2024,
                probability=probability,
                confidence="high",
                kelly=_kelly_fraction(probability),
                suggested_weight=0.0,
                contributing_features={},
                feature_values={},
            )
            for i in range(n)
        ]

    def test_top_50_equal_weight(self):
        """Exactly 50 stocks get 2% weight each."""
        scored = self._make_scored(80, probability=0.35)
        _build_portfolio(scored, lambda _: None)

        in_portfolio = [s for s in scored if s.suggested_weight > 0]
        assert len(in_portfolio) == ML_TOP_N
        expected_weight = round(1.0 / ML_TOP_N, 4)
        for s in in_portfolio:
            assert s.suggested_weight == expected_weight

    def test_fewer_than_50_all_included(self):
        """When fewer than 50 stocks, all get the equal weight."""
        scored = self._make_scored(10, probability=0.35)
        _build_portfolio(scored, lambda _: None)

        in_portfolio = [s for s in scored if s.suggested_weight > 0]
        assert len(in_portfolio) == 10
        expected_weight = round(1.0 / ML_TOP_N, 4)
        for s in in_portfolio:
            assert s.suggested_weight == expected_weight

    def test_no_minimum_probability(self):
        """Even very low probability stocks are included if in top 50."""
        scored = self._make_scored(5, probability=0.01)
        _build_portfolio(scored, lambda _: None)

        for s in scored:
            assert s.suggested_weight > 0  # All get weight, no minimum probability

    def test_weights_sum_to_one(self):
        """With 50+ stocks, portfolio utilisation is exactly 100%."""
        scored = self._make_scored(60, probability=0.40)
        _build_portfolio(scored, lambda _: None)

        total = sum(s.suggested_weight for s in scored)
        assert abs(total - 1.0) < 0.001

    def test_no_country_cap(self):
        """All stocks from same country are included — no country constraints."""
        scored = self._make_scored(30, probability=0.35, country="US")
        _build_portfolio(scored, lambda _: None)

        # All 30 should be in portfolio (< 50)
        in_portfolio = [s for s in scored if s.suggested_weight > 0]
        assert len(in_portfolio) == 30

    def test_no_sector_cap(self):
        """All stocks from same sector are included — no sector constraints."""
        scored = self._make_scored(40, probability=0.35, sector="Tech")
        _build_portfolio(scored, lambda _: None)

        # All 40 should be in portfolio (< 50)
        in_portfolio = [s for s in scored if s.suggested_weight > 0]
        assert len(in_portfolio) == 40
