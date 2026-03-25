# PRD 7.7 — Relative Outperformance Target

**Status**: Complete
## Problem

Two previous ML target definitions failed to produce practical stock selection:

- **PRD 7.5 "Winner" (100%+ return)**: Model became a lottery ticket picker. 3.2x lift over random in winner identification, but median pick loses money (-20% median for top 10). Strategy depends entirely on catching extreme +1000% outliers.
- **PRD 7.6 "Risk-adjusted" (30%+ return, -25% max DD)**: Worse than random on 2024 holdout. The target is regime-dependent — base rate swings from 4.3% (2019) to 20.7% (2020). Model learned "pick Indian stocks" because India historically had the best calm-and-rising regime. 85% of top 100 picks were Indian stocks.

Both targets encode market regime into the label. In a bear year, almost nothing qualifies as an absolute winner, so the model learns to predict macro conditions rather than stock-level quality.

## Solution

Define winners by **relative outperformance**: beat your country's median stock by 20%+ over 12 months.

| Property | Old "Winner" | Risk-Adjusted | Relative Outperformance |
|----------|-------------|---------------|------------------------|
| Definition | Return >= 100% | Return >= 30%, DD >= -25% | Excess return >= 20% |
| Base rate | 4.5% | 12.3% | ~27% |
| Rate stability | Moderate | Very poor (4-21%) | Very stable (23-33%) |
| Regime independent | No | No | Yes |

A stock that goes up 5% when its country peers drop 20% is an outperformer. A stock that goes up 30% in a market up 40% is not. This forces the model to learn stock-level fundamentals and momentum quality rather than macro regime.

## Changes

### `app/predict/parquet_dataset.py`

Add `relative_to_country: bool = False` parameter. When `True` with `return_threshold` set:
- Compute country-year median `fwd_return_12m` from the data
- Compute excess return per row
- Label based on excess return vs threshold
- Filter rows needing non-null `fwd_return_12m`

### `app/cli.py`

Add `--relative-to-country` flag to `train-model`.

### `app/predict/model.py`

Store `relative_to_country` in `train_config`.

### `tests/test_parquet_dataset.py`

Add tests for relative label computation.

## Files

| File | Action |
|------|--------|
| `docs/product/prd_7_7.md` | New |
| `app/predict/parquet_dataset.py` | Modify |
| `app/cli.py` | Modify |
| `app/predict/model.py` | Modify |
| `tests/test_parquet_dataset.py` | Modify |

## Verification

1. `pytest -q` — all tests pass
2. Train with `--return-threshold 0.20 --relative-to-country` plus investability filters
3. Verify holdout decile: monotonic winner rate and median excess returns
4. Model stored in DB with `relative_to_country` in `train_config`
