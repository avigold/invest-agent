# PRD 9.0 — Align ML Scoring & Backtest with Validated Methodology

**Product**: investagent.app
**Version**: 9.0 (major)
**Date**: 2026-03-07
**Status**: Complete
**Milestone**: 9
**Priority**: MISSION CRITICAL

---

## 1. Context

The validated backtest (`scripts/gen_excel_deduped.py`, seed 32) achieved 84.5% average annual return across 2018–2024. Users will make real investment decisions based on the picks this model produces. The production system must replicate the validated methodology exactly — any divergence means users are relying on unvalidated results.

## 2. Problem statement

Neither the production scoring pipeline nor the in-app backtest replicates the validated methodology. Investigation uncovered **three separate portfolio construction methods** across the codebase, and the only validated one is used by none of the production code.

### 2.1 Divergences: validated script vs in-app backtest

| # | Aspect | Validated (`gen_excel_deduped.py`) | In-app backtest (`backtest.py`) |
|---|--------|--------|---------|
| 1 | Predictions used | Raw LightGBM scores | Platt-calibrated probabilities |
| 2 | Deduplication | By company name (`.strip().lower()`) | None |
| 3 | Portfolio construction | Top 50, equal weight (2% each) | Kelly criterion with constraints |
| 4 | Kelly parameters | N/A | avg_win=3.0, avg_loss=-0.50, fraction=0.25 |
| 5 | Minimum probability | None | 5% threshold |
| 6 | Position constraints | None | 10% max per position |
| 7 | Sector constraints | None | 30% max per sector |
| 8 | Sector data | Not used | Hardcoded to `"Unknown"` |
| 9 | Return capping | No cap | Capped at -1.0 per position |
| 10 | Hit definition | Outperformer = label==1 | Hit = forward_return >= 3.0 |

### 2.2 Divergences: validated script vs production scorer

| # | Aspect | Validated | Production scorer (`parquet_scorer.py`) |
|---|--------|-----------|----------------------------------------|
| 11 | Portfolio construction | Top 50 equal weight | Kelly + country + sector caps |
| 12 | Min probability | None | 15% |
| 13 | Kelly parameters | N/A | avg_win=0.42, avg_loss=-0.15 |
| 14 | Country constraints | None | 30% max per country |

### 2.3 Two intentionally separate scoring systems

The codebase has two separate scoring systems that serve different purposes. They must never be conflated:

| System | Purpose | Files | Data source | Features |
|--------|---------|-------|-------------|----------|
| **ML/Parquet** | LightGBM model predictions | `parquet_scorer.py`, `parquet_dataset.py`, `model.py` | Parquet file | 186 features |
| **Deterministic** | Fundamentals-based scoring | `scorer.py`, `strategy.py`, `features.py` | Database (`CompanyScore`) | 22 features |

These are **completely independent systems**. The deterministic scorer is not broken — it serves its own purpose. This PRD addresses only the ML/Parquet system.

### 2.4 What is verified correct

- Model in DB matches `data/models/seed32_v1.pkl` (boosters, Platt params, feature names — byte-identical)
- Model config matches validated script: seed 32, 24 countries, relative outperformance, 20% threshold, $500k min dollar volume
- Parquet scorer's feature pipeline is correct: reads same 186 features from training Parquet file
- Platt scaling is monotonic: top 50 by raw score = top 50 by calibrated probability (ranking preserved)

## 3. The validated methodology (to be replicated exactly)

From `scripts/gen_excel_deduped.py`:

1. Load features from Parquet (186 features, same as training data)
2. Apply investability filters: 24 allowed countries, min $500k dollar volume
3. Keep most recent fiscal year per ticker
4. Generate predictions (raw or Platt-calibrated — ranking is identical)
5. Sort by prediction score descending
6. Deduplicate by company name (`.strip().lower()`)
7. Select top 50 unique companies
8. Assign equal weight: 2% each (1/50)

No minimum probability threshold. No Kelly sizing. No sector/country caps. All 50 get in.

## 4. Implementation plan — step-by-step with verification

### Step 1: Back up the model

**Action**: Create additional backup of `data/models/seed32_v1.pkl`.
**Verification**: Byte-for-byte comparison of original and backup.

### Step 2: Add company names to ParquetDataset

**Action**: Extend `ParquetDataset` in `parquet_dataset.py` to store `company_names: list[str]` alongside `tickers`. The backtest needs company names for deduplication.

**File**: `app/predict/parquet_dataset.py`

**Verification**: Load dataset, confirm `len(ds.company_names) == len(ds.tickers)`.

### Step 3: Fix production portfolio construction

**Action**: Replace `_build_portfolio()` in `parquet_scorer.py` with top-50 equal-weight. Remove Kelly sizing constants. Keep `_kelly_fraction()` and confidence tiers as display-only fields.

**File**: `app/predict/parquet_scorer.py`

**New logic**: Top 50 stocks (already sorted desc, already deduped) get `suggested_weight = 0.02`. Rest get `0.0`.

**Verification**:
- Run CLI scorer on training Parquet
- Confirm exactly 50 positions with 2% weight each
- Confirm portfolio utilisation = 100.0%
- Compare top 50 tickers against validated script's 2024 picks

### Step 4: Fix in-app backtest

**Action**: Rewrite `backtest.py` to use top-50 equal-weight with company deduplication per fold. Remove dependency on `strategy.py`.

**File**: `app/predict/backtest.py`

**New logic per fold**:
1. Get predictions (Platt-calibrated — ranking preserved)
2. Sort by probability descending
3. Deduplicate by company name (`.strip().lower()`)
4. Select top 50
5. Equal weight: `weight = 1/50 = 0.02`
6. Portfolio return: `sum(weight * actual_return)` for all 50 positions
7. Hit = outperformer (label == "winner")

**Verification**:
- Retrain model via CLI with same config
- Compare per-fold picks and returns against `gen_excel_deduped.py` output
- Same 50 stocks should appear for each fold year

### Step 5: Document the two scoring systems

**Action**: Add clear documentation to CLAUDE.md and module-level docstrings distinguishing the ML/Parquet system from the deterministic system. Add to persistent memory.

**Files**: `CLAUDE.md`, `app/predict/parquet_scorer.py` (docstring), `app/predict/scorer.py` (docstring)

### Step 6: End-to-end verification

- [ ] Model in DB matches `data/models/seed32_v1.pkl`
- [ ] ML scorer uses all 186 features from Parquet
- [ ] ML scorer selects top 50 by probability, deduped by company name
- [ ] All 50 get exactly 2% weight
- [ ] Portfolio utilisation = 100.0%
- [ ] In-app backtest uses same methodology (top 50, equal weight, deduped)
- [ ] In-app backtest per-fold picks match validated script
- [ ] In-app backtest per-fold returns match validated script
- [ ] No Kelly sizing in any ML portfolio construction code path
- [ ] Kelly fraction and confidence tier remain as display-only fields
- [ ] CLAUDE.md documents both scoring systems clearly
- [ ] Module docstrings distinguish ML vs deterministic systems
- [ ] `pytest -q` passes
- [ ] Build succeeds

## 5. Files changed

| File | Action |
|------|--------|
| `docs/product/prd_9_0.md` | Create — this PRD |
| `app/predict/parquet_scorer.py` | Modify — replace `_build_portfolio()` with top-50 equal weight; clarify docstring as ML system |
| `app/predict/parquet_dataset.py` | Modify — add `company_names` to `ParquetDataset` |
| `app/predict/backtest.py` | Modify — rewrite to top-50 equal weight with dedup |
| `app/predict/scorer.py` | Modify — clarify docstring as deterministic system |
| `CLAUDE.md` | Modify — add scoring systems documentation + model protection rules |
| `app/predict/README.md` | Create — document both scoring systems and file membership |
| `data/models/seed32_v1_backup.pkl` | Create — additional model backup |

## 6. Files NOT changed

| File | Reason |
|------|--------|
| `app/predict/model.py` | Model loading, Platt scaling, serialisation — all correct |
| `app/predict/strategy.py` | Part of deterministic system — not in scope |
| `app/predict/features.py` | Part of deterministic system — not in scope |
| `app/jobs/handlers/prediction_score.py` | Part of deterministic system — not in scope |
| `scripts/gen_excel_deduped.py` | Ground truth reference — never modified |
| `data/models/seed32_v1.pkl` | Original model backup — never modified |

## 7. Risk assessment

| Risk | Mitigation |
|------|------------|
| Model deleted or corrupted | Backup in Step 1; no code path deletes model blob |
| Backtest results differ from validated | Step 6: compare pick-by-pick against ground truth |
| Feature pipeline drift | Parquet scorer reads same file used for training |
| Platt scaling changes ranking | Mathematically impossible (monotonic transformation) |
| Scoring systems confused again | Step 5: documentation in CLAUDE.md, module docstrings, persistent memory |

## 8. Safeguards

### 8.1 Safeguards against confusing the two scoring systems

**A. CLAUDE.md documentation** — Dedicated `## Scoring systems` section listing both systems with exact file paths, stating they are completely independent, stating: "Never import from one system into another."

**B. Module-level docstrings** — Every file in each system gets a banner:
- ML files: `"""ML/PARQUET SCORING SYSTEM — Do not confuse with the deterministic system."""`
- Deterministic files: `"""DETERMINISTIC SCORING SYSTEM — Do not confuse with the ML system."""`

**C. Persistent memory** — Add both systems to `MEMORY.md` with NEVER CONFLATE warning.

**D. Directory-level README** — `app/predict/README.md` listing both systems and their file membership.

**E. Preflight check** — Before modifying any `app/predict/` file, read `app/predict/README.md` to confirm which system the file belongs to.

### 8.2 Safeguards against model deletion or corruption

**A. Multiple backups** — Model stored in three places: DB, `seed32_v1.pkl`, `seed32_v1_backup.pkl`.

**B. Model integrity verification** — Before any prediction file change, verify DB model matches disk backup.

**C. Never-delete rules** — Added to CLAUDE.md: never delete model files, never run SQL against `prediction_models`, never modify `model.py` serialise/deserialise without approval, never modify `gen_excel_deduped.py`.

**D. Pre-commit verification** — Before committing prediction file changes: model integrity check, `pytest -q`, verify backups exist.

**E. Ground truth immutability** — Comment at top of `gen_excel_deduped.py`: `# GROUND TRUTH — DO NOT MODIFY`.

## 9. Out of scope

- Retraining the model
- Changing the feature pipeline or data sources
- The deterministic scoring system (`scorer.py`, `strategy.py`, `features.py`, `prediction_score.py`)
- UI changes to ML Picks display
- Composite/ML blending
