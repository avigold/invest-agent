# PRD 9.2 — Correct Cross-Listed Tickers to Home Listings

**Product**: investagent.app
**Version**: 9.2
**Date**: 2026-03-08
**Status**: Complete
**Priority**: HIGH

---

## Context

The Parquet dataset contains multiple exchange listings for the same company. Apple Inc. appears as AAPL (US), APC.DE (Frankfurt), APC.F (Frankfurt), AAPL.MX (Mexico), AAPL.NE (Netherlands). The model scores all listings and the post-scoring dedup keeps whichever scored highest. This produced recommendations like APC.DE, GOOGL.SW, IBM.DE — foreign cross-listings that no user should buy when the primary listing exists with far better liquidity.

The fix: let the model score all listings (the foreign exchange may have a legitimately better signal), but after dedup, correct the ticker to the home-country listing. The probability from whichever listing scored highest is preserved.

## Model protection — THIS IS NOT OPTIONAL

The model (`seed32_v1.pkl`, seed 32) produces 84.5% average annual return across 2018–2024. If this model is deleted, corrupted, or overwritten, there is no guarantee it can be reproduced.

This PRD modifies ONE file in `app/predict/`: `parquet_scorer.py`. The change is to the post-scoring ticker correction only. The model itself, its training, its serialisation, and its features are untouched.

**Rules:**
- Never delete or overwrite model files
- Never run SQL against `prediction_models`
- Never modify `model.py` serialise/deserialise without explicit user approval
- Never modify `scripts/gen_excel_deduped.py`

## Change

**File**: `app/predict/parquet_scorer.py`

1. Added `_EXCHANGE_COUNTRY` mapping (ticker suffix → ISO2 country code) and `_exchange_country()` helper.

2. Before scoring, build a `_home_ticker_map` (normalized company name → home ticker). The home ticker is the one whose exchange country matches `country_iso2`.

3. After the existing post-scoring company name dedup, correct the winning ticker to the home listing from the map. The probability is kept from whichever listing scored highest.

**Result**: 913 tickers corrected to home listings. AAPL instead of APC.DE, GOOG instead of GOOGL.SW, IBM instead of IBM.DE.

## Files changed

| File | Change |
|------|--------|
| `docs/product/prd_9_2.md` | Create — this PRD |
| `app/predict/parquet_scorer.py` | Add exchange-country mapping + post-scoring ticker correction |
| `tests/test_parquet_scorer.py` | Add tests for exchange country mapping and ticker correction |

## Files NOT changed

| File | Reason |
|------|--------|
| `app/predict/model.py` | Model untouched |
| `app/predict/backtest.py` | Backtest uses ParquetDataset directly; can be addressed separately |
| `scripts/gen_excel_deduped.py` | Ground truth — never modified |
| `data/models/*` | Model files never modified |

## Verification

- [x] Model integrity verified (SHA-256 unchanged)
- [x] AAPL appears for Apple Inc. (prob=54.4% from best exchange)
- [x] GOOG appears for Alphabet Inc. (prob=87.6%)
- [x] IBM appears for IBM (prob=86.1%)
- [x] 913 tickers corrected to home listings
- [x] Re-score universe: 50 positions at 2% each, sum = 1.00
- [x] `pytest -q` passes (532)
- [x] `npm run build` succeeds
