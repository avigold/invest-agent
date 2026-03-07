# PRD 7.4 — Comprehensive ML Training Dataset Exporter

## Problem

We have 45,698 companies with FMP fundamentals and JSONB price history (~173M daily data points). FMP artefacts stored on disk contain 140 financial fields per company per year, but we currently extract only 9 into `company_series_points`. The existing `app/predict/` module uses only 22 features. To discover micro-advantages for predictive models, we need to export everything available.

## Solution

Build a Parquet exporter that reads raw FMP artefact JSON files directly, computes ~200 features per company per fiscal year, and outputs a training-ready dataset.

## Output Files

1. **`training_features.parquet`** — One row per company per fiscal year (~450k rows, ~200 columns)
2. **`price_series.parquet`** (optional) — One row per company per trading day (~173M rows, partitioned by year)

## Feature Inventory (~200 columns)

- **Identifiers (6):** ticker, company_name, country_iso2, gics_code, fiscal_year, statement_date
- **Raw Income Statement (30):** All numeric FMP fields (revenue, grossProfit, ebitda, eps, etc.)
- **Raw Balance Sheet (50):** All numeric FMP fields (totalAssets, totalDebt, netDebt, etc.)
- **Raw Cash Flow (30):** All numeric FMP fields (freeCashFlow, operatingCashFlow, capex, etc.)
- **Derived Ratios (~40):** Profitability (8), leverage (6), efficiency (5), quality/accruals (5), capital allocation (4), growth YoY (6), growth trend (3), Piotroski F-Score (1)
- **Price Features (~25):** Multi-horizon momentum, volatility, drawdown, volume dynamics
- **Context (~10):** Country/industry scores, macro rates
- **Forward Returns (6):** 3m/6m/12m/24m returns + max drawdown + winner label

## Files Changed

| File | Action |
|---|---|
| `docs/product/prd_7_4.md` | New — this PRD |
| `app/export/__init__.py` | New — module init |
| `app/export/features.py` | New — feature extraction from raw FMP JSON |
| `app/export/training_dataset.py` | New — async exporter, Parquet writer |
| `app/cli.py` | Modify — add `export-training` command |
| `pyproject.toml` | Modify — add `pyarrow>=15.0` |
| `tests/test_export_features.py` | New — unit tests |
| `tests/test_export_training.py` | New — integration test |

## Acceptance Criteria

1. `python -m app.cli export-training --output-dir /tmp/export` produces `training_features.parquet`
2. Output has ~200 columns and ~450k rows
3. All derived ratios compute correctly (verified by unit tests)
4. Forward returns use no look-ahead bias
5. `--include-prices` produces `price_series.parquet`
6. `--countries US` filters output
7. All tests pass
