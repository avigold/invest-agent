# PRD 7.6 — Risk-Adjusted Winner Label

**Status**: Complete
## Problem

The PRD 7.5 model (LightGBM, walk-forward CV) predicts "winners" defined as stocks with 100%+ 12-month returns. Holdout analysis on 2024 data reveals the model is a "lottery ticket picker":

- Top-10 picks have **median return of -20%** — the typical pick loses money
- 80% of top-100 picks don't double; many lose -50% to -95%
- Average returns are lifted by extreme outliers (+1000%)
- Model's #1 feature is volatility — it learned "high vol + distress = potential 10-bagger"
- Decile median returns are **inverted**: model's top bucket has lower median than bottom bucket

The 4.5% base rate (stocks that double) forces the model to target extreme outliers, producing a high-variance strategy unsuitable for portfolio construction.

## Solution

Redefine the positive label as **risk-adjusted winner**: a stock that returns 30%+ in 12 months with max drawdown no worse than -25%.

| Metric | Old "Winner" | Risk-Adjusted Winner |
|--------|-------------|---------------------|
| Definition | 12m return >= 100% | 12m return >= 30% AND max DD >= -25% |
| Base rate | 4.5% | 12.3% |
| Median return | +180% | +54% |
| Median max DD | -35% | -17% |
| Overlap | — | 18% of risk-adj are old winners |

This target captures stocks with strong, smooth returns — the kind an investor would actually want to hold.

## Changes

### `app/predict/parquet_dataset.py`

Add `return_threshold` and `max_dd_threshold` parameters to `load_parquet_dataset()`. When both set:
- Filter out rows with null `fwd_max_dd_12m`
- Compute labels from returns + drawdown instead of `fwd_label` column
- Log the label definition and base rate

Add corresponding fields to `ParquetDataset` dataclass for downstream reference.

### `app/cli.py`

Add `--return-threshold` and `--max-dd-threshold` options to `train-model` command. Pass through to dataset loading.

### `app/predict/model.py`

Store `return_threshold` and `max_dd_threshold` in `train_config` so the model records what label definition was used.

### `tests/test_parquet_dataset.py`

Add tests for risk-adjusted label mode: correct label computation, null drawdown filtering, default mode unchanged.

## Files

| File | Action |
|------|--------|
| `docs/product/prd_7_6.md` | New |
| `app/predict/parquet_dataset.py` | Modify |
| `app/cli.py` | Modify |
| `app/predict/model.py` | Modify |
| `tests/test_parquet_dataset.py` | Modify |

## Verification

1. `pytest -q` — all tests pass
2. Train with `--return-threshold 0.30 --max-dd-threshold -0.25` plus investability filters
3. Verify decile analysis shows monotonic winner rate and monotonic median returns
4. Model stored in DB with thresholds in `train_config`
