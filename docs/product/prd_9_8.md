# PRD 9.8 — Filter ADRs, Duplicate Listings, and Address Currency Mixing

**Product**: investagent.app
**Version**: 9.8
**Date**: 2026-03-09
**Status**: Complete
**Priority**: HIGH

---

## Problem

### 1. ADRs and OTC foreign shares in predictions

The ML scoring pipeline includes ADRs (American Depositary Receipts) and OTC foreign shares alongside primary listings. SAFRY (US OTC ADR for Safran) appears in predictions instead of SAF.PA (Euronext Paris primary listing). The same company appears 2–3 times under different tickers, and company name dedup fails because FMP uses slightly different names across listings ("Safran S.A." vs "Safran SA").

**Scope in current parquet**:
- 93 suspected ADR tickers (US, 5+ chars ending Y)
- 119 suspected OTC foreign tickers (US, 5+ chars ending F)
- Of the 93 ADRs, 74 already have a matching primary listing in the dataset

### 2. Currency mixing in raw features

The model uses 186 features: 123 raw financial statement values (revenue, assets, etc.) and 63 ratio/derived features. Raw values are in each company's reporting currency — Taisei's revenue is ¥2.15 trillion while Apple's is $383 billion. These are fed to the model without currency normalisation.

**How bad is this?**

Mitigating factors:
- The 63 ratio features (margins, ROE, growth rates, etc.) are currency-agnostic and account for 54.3% of total feature importance
- The top 30 features by importance contain only 1 raw value feature (`cf_accountsPayables` at #28)
- LightGBM uses tree splits, not linear coefficients — it can learn that "revenue > 1e12 AND country = JP" means something different from "revenue > 1e12 AND country = US"
- The `cat_country_iso2` feature (#1 by importance at 2.25%) gives the model a signal to condition on
- The model was validated at 84.5% average annual return across a multi-country universe with this exact currency mixing — so it works empirically

However:
- Dollar volume (`dollar_volume_30d`) mixes currencies despite its name — this directly affects the investability filter (`min_dollar_volume >= 500,000`), potentially excluding liquid stocks in weak-currency countries or including illiquid ones in strong-currency countries
- Raw features like `inc_revenue`, `bal_totalAssets` create country-clustered splits rather than meaningful cross-country comparisons
- This is a latent source of bias that could interact poorly with the ADR problem (an ADR reports in USD while the primary listing reports in local currency, creating a within-company inconsistency)

**Recommendation**: Address currency mixing in a future PRD (normalisation to USD, or dropping raw value features in favour of ratios). The validated backtest proves the current model works despite this issue, and fixing it requires retraining. This PRD focuses on the ADR filtering, which is the user-visible problem.

## Data available from FMP

The FMP **profile** endpoint returns:
- `isAdr` (boolean) — true for ADRs like SAFRY
- `exchange` / `exchangeShortName` — "OTC" for OTC-traded securities
- `isin` (string) — same ISIN for same issuer (dedup key)
- `country` — issuer country (FR for Safran regardless of listing)

The FMP **screener** endpoint returns `exchangeShortName` but not `isAdr`.

## Solution

### Phase 1: Database enrichment

**Add columns to `companies` table** (migration `0013`):
- `is_adr: Boolean, default false` — true for depositary receipts
- `exchange_short: String(20), nullable` — exchange code from FMP (e.g. "NYSE", "OTC", "PAR")
- `isin: String(20), nullable` — ISIN for issuer-level dedup

**New CLI command `enrich-companies`**:
- Batch-call FMP profile endpoint for all companies missing `is_adr`/`exchange_short`
- Populate `is_adr`, `exchange_short`, `isin` from profile response
- Rate limit: ~10 calls/second (FMP limit)
- Log progress; idempotent (skip already-enriched rows)
- Processable as a job handler too (`enrich_companies`)

### Phase 2: Filter at discover time

**Modify `discover_companies_handler`** and CLI `discover-companies`:
- Remove `"OTC"` and `"PNK"` from `_EXCHANGES` list — these are the primary source of ADR/foreign OTC contamination
- Store `exchange_short` from screener result's `exchangeShortName` field on insert
- After inserting new companies, batch-enrich via FMP profile to populate `is_adr` and `isin`

### Phase 3: Filter at scoring time (immediate fix)

**Modify `parquet_scorer.py` → `score_from_parquet()`**:
- After loading parquet, before scoring, exclude rows matching ADR/OTC heuristics:
  - Ticker has no dot AND length >= 5 AND ends in `Y` → likely ADR
  - Ticker has no dot AND length >= 5 AND ends in `F` → likely OTC foreign
  - Ticker contains `.F` AND `country_iso2 != "DE"` → Frankfurt cross-listing of non-German company
- Log how many rows were excluded
- This is a heuristic safety net for the existing parquet — the primary defence going forward is the DB-level `is_adr` flag

**Improve company name normalisation in dedup**:
- Before comparing, strip trailing punctuation and common suffixes: `S.A.`, `SA`, `Inc`, `Inc.`, `Ltd`, `Ltd.`, `Corp`, `Corp.`, `Co`, `Co.`, `PLC`, `plc`, `AG`, `SE`, `NV`, `N.V.`, `Limited`, `Corporation`
- This catches "Safran S.A." vs "Safran SA"

### Phase 4: Filter at parquet export time

**Modify `training_dataset.py` → `export_training_dataset()`**:
- When building the company query, exclude `Company.is_adr == true`
- Exclude `Company.exchange_short == "OTC"` (if column populated)
- This prevents ADRs from entering future training data

### Phase 5: Re-export and retrain (user-triggered, NOT part of this PRD)

After enrichment:
- Re-export training parquet (filtered) via `export-training-data`
- Retrain model to get clean training data without ADR contamination
- This step requires explicit user approval per ML protection rules
- Will be covered in a separate PRD if desired

## Model protection

- No changes to `app/predict/model.py` — training logic and hyperparameters untouched
- No changes to `scripts/gen_excel_deduped.py` — golden reference, never modified
- No changes to `data/models/*` — golden model files, never modified
- The scoring-time filter (Phase 3) is additive — it removes bad rows before they reach the model, it does not alter the model itself
- Existing model and its DB scores are not modified

## Files changed

| File | Change |
|------|--------|
| `docs/product/prd_9_8.md` | Create — this PRD |
| `alembic/versions/0013_add_company_listing_metadata.py` | **New** — migration adding `is_adr`, `exchange_short`, `isin` |
| `app/db/models.py` | Add three columns to Company |
| `app/cli.py` | Add `enrich-companies` CLI command |
| `app/jobs/handlers/discover_companies.py` | Remove OTC/PNK from exchanges, store exchange_short on insert |
| `app/predict/parquet_scorer.py` | ADR/OTC ticker heuristic filter + improved name normalisation in dedup |
| `app/export/training_dataset.py` | Exclude is_adr/OTC companies from export |

## Files NOT changed

| File | Reason |
|------|--------|
| `app/predict/model.py` | No changes to training logic or hyperparameters |
| `scripts/gen_excel_deduped.py` | Golden reference — never modified |
| `data/models/*` | Golden model files — never modified |
| `app/predict/parquet_dataset.py` | Training data loader unchanged — filtering happens at export |

## Acceptance criteria

1. Migration adds `is_adr`, `exchange_short`, `isin` columns; `alembic upgrade head` succeeds
2. `enrich-companies` CLI command populates listing metadata from FMP profiles
3. After enrichment, `SELECT count(*) FROM companies WHERE is_adr = true` returns a non-zero count
4. Discover handler no longer scans OTC/PNK exchanges; `exchange_short` stored on insert
5. `score_from_parquet()` excludes ADR/OTC heuristic tickers before scoring; SAFRY-type results do not appear in predictions
6. Company name dedup catches "Safran S.A." = "Safran SA" and similar
7. Training data export excludes `is_adr` companies
8. Existing golden model and its scores are not modified
9. `npm run build` succeeds
