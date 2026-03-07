# CLAUDE.md — Invest Agent (investagent.app)

## Product intent
Invest Agent is a multi-tenant research platform. Each user submits research jobs; the system ingests and compiles country/industry/company data, computes deterministic scores, stores evidence with lineage, and exposes an API + UI for decision packets.

The interaction model mirrors the job-queue-per-user design used in the user’s chess analysis SaaS (JobRegistry + JobQueue + SSE logs), adapted to investment research workflows. :contentReference[oaicite:0]{index=0}

## Non-negotiables
- Deterministic scoring paths with explicit `calc_version` and `summary_version`.
- Evidence discipline: summaries must be assembled from stored facts only.
- Idempotent ingestion/jobs: safe to re-run with unique constraints and upserts.
- Per-user job isolation and plan gating.
- Failures are visible: job logs are first-class and streamable.
- Minimal ambiguity: implement exactly what `SPEC.md` and `ACCEPTANCE.md` say.

## Scoring Systems (two separate, independent systems — NEVER conflate)

This codebase has TWO completely independent scoring systems. They serve different purposes, use different data, and must NEVER be confused with each other. Never import from one system into another. Never apply ML methodology to deterministic files or vice versa.

### ML/Parquet System
- **Purpose**: LightGBM model predictions trained on comprehensive Parquet data (186 features)
- **Files**: `app/predict/parquet_scorer.py`, `app/predict/parquet_dataset.py`, `app/predict/model.py`, `app/predict/backtest.py`
- **Data source**: `data/exports/training_features.parquet`
- **Invoked via**: CLI commands (`train_model`, `score_universe`)
- **Portfolio construction**: Top-50 equal weight (2% each), deduped by company name — matches validated backtest
- **Validated result**: 84.5% average annual return across 2018–2024 (seed 32)

### Deterministic System
- **Purpose**: Fundamentals-based scoring from CompanyScore database data (22 features)
- **Files**: `app/predict/scorer.py`, `app/predict/strategy.py`, `app/predict/features.py`
- **Data source**: Database (`CompanyScore` table)
- **Invoked via**: `prediction_score.py` job handler, `prediction_train.py` job handler
- **Portfolio construction**: Kelly criterion with sector/position constraints (in strategy.py)

### Preflight check
Before modifying ANY file in `app/predict/`, read `app/predict/README.md` to confirm which system the file belongs to. Modifying the wrong system is a blocking error.

## ML Model Protection (CRITICAL — read every word)

Trained ML models are the most valuable asset in this project. Violating any rule below is a **blocking failure**. No exceptions. No shortcuts.

### Rules

1. **NEVER delete a PredictionModel row** from the database unless the user explicitly says "delete model X". Cascade deletes to PredictionScore are equally dangerous.
2. **NEVER retrain or re-score** without the user's explicit approval in that conversation. "Score the universe" does NOT mean "retrain first." Ask.
3. **NEVER modify `PARQUET_PARAMS`**, `PARQUET_FOLD_YEARS`, `PARQUET_HOLDOUT_YEAR`, or any training hyperparameter in `app/predict/model.py` without explicit user approval.
4. **NEVER modify or delete** files in `data/models/`, `data/exports/backtest_portfolio*.xlsx`, `scripts/gen_excel_deduped.py`, or `scripts/seed_sweep*.py`. These are golden artifacts.
5. **Every trained model** must be saved to BOTH the database AND a file in `data/models/` with a descriptive name. The DB can be wiped; the file cannot be easily recovered.
6. **Every training run** must log the full config (seed, countries, thresholds, all hyperparameters) to both the model's `config` JSONB field and the console output.
7. **Before scoring**, always confirm which model ID to use. Never assume "latest."
8. **NEVER delete, overwrite, or modify** `data/models/seed32_v1.pkl` or `data/models/seed32_v1_backup.pkl`.
9. **NEVER run SQL** that deletes from `prediction_models` table.
10. **NEVER modify** `app/predict/model.py` serialise/deserialise methods without explicit user approval.
11. **NEVER modify** `scripts/gen_excel_deduped.py` — it is the ground truth reference.
12. **Before any predict/ change**, verify model integrity (DB blob matches disk backup).

### Golden Model Config (Seed 32)

This is the configuration that produced 84.5% average annual return across 2018-2024 backtests. It must be reproducible at any time.

```
Seed: 32 (set on seed, data_random_seed, feature_fraction_seed, bagging_seed)
Countries (24, NO INDIA): US,GB,CA,AU,DE,FR,JP,CH,SE,NL,KR,BR,ZA,SG,HK,NO,DK,FI,IL,NZ,TW,IE,BE,AT
min_dollar_volume: 500,000
max_return_clip: 10.0
return_threshold: 0.20
relative_to_country: True
half_life: 7.0
min_fiscal_year: 2000
num_leaves: 63
min_data_in_leaf: 50
learning_rate: 0.05
feature_fraction: 0.6
bagging_fraction: 0.7
bagging_freq: 5
num_boost_round: 1000
early_stopping_rounds: 50
scale_pos_weight: NOT USED (critical — production train_walk_forward_parquet adds this but the backtest script does not)
Deduplication: by company_name.strip().lower(), keep highest-scored listing
```

Reproduction script: `scripts/gen_excel_deduped.py`
Backup sweep scripts: `scripts/seed_sweep.py`, `scripts/seed_sweep_no_india.py`
Model blob backup: `data/models/seed32_v1.pkl` (after training)
Backtest output: `data/exports/backtest_portfolio_deduped.xlsx`

## Scope ordering
Build in this order, with acceptance tests per milestone:
1) Auth + users + subscriptions + job system (multi-tenant)
2) Country module v1 (top 10 investable countries)
3) Industry module v1 (template-driven)
4) Company module v1 (US filings-first), then expand

## Stack
- Python 3.11+
- Web: FastAPI
- DB: Postgres
- Migrations: Alembic
- HTTP client: httpx
- Background jobs: simple in-process worker pool for MVP, then Redis + RQ/Celery if needed
- Streaming logs: SSE endpoint per job
- Deploy: Docker Compose for dev; systemd + gunicorn/uvicorn behind nginx for prod

## Auth and plans
- Auth provider for MVP: Google OAuth (OIDC) or passwordless email; keep modular for later.
- Stripe for billing: Free/Pro. Admin/titled roles may bypass limits (same idea as `_effective_plan()` in the chess app). :contentReference[oaicite:1]{index=1}

Plan gating primitives:
- Per-command monthly quotas for Free.
- Pro has unlimited jobs (subject to global concurrency limits).

## Job model (core of the platform)
Every user action that triggers compute creates a job row.
Jobs are executed asynchronously with:
- a global concurrency limit for heavy jobs
- optional per-user concurrency limit
- separate “light” jobs that can bypass the heavy queue when safe

Jobs stream logs live over SSE.
On service restart, any job marked `running` is set to `cancelled` (no attempt to resume subprocess state). :contentReference[oaicite:2]{index=2}

### Job commands (initial set)
- `country_refresh` (compute country series + scores + packet)
- `industry_refresh` (compute industry scores + packet)
- `company_refresh` (ingest filings/market data + scores + packet)
- `universe_refresh` (batch refresh for allowed universe)
- `packet_build` (rebuild decision packets without re-ingesting)
- `backfill` (historical series/filings backfill)

Each job has:
- `params` JSON (validated against a pydantic schema)
- status lifecycle: `queued -> running -> done|failed|cancelled`
- timestamps: queued/started/finished
- output pointers (artefacts, packet ids)
- `log_text` (persisted) and stream queue for live output

## Data sourcing (by layer)
- Country:
  - World Bank Indicators API (broad macro, slower cadence)
  - FRED (rates/credit where applicable)
  - GDELT-derived political stability index (monthly, deterministic transform)
  - Equity index proxy (config-mapped symbol) for return/drawdown
- Industry:
  - Template-driven rubric + macro regime inputs from country layer
  - Optional GDELT “regulatory heat / disruption heat” counters (later)
- Company:
  - US first: SEC EDGAR APIs + XBRL facts extraction
  - Market data: EOD provider (swappable)
  - Identifier mapping: OpenFIGI (optional)

## Evidence discipline (hard requirement)
- All raw fetches are stored as `artefacts` with:
  - source metadata
  - fetch time window
  - content hash
  - storage URI (local dir in dev; S3-compatible later)
- All normalised points reference an `artefact_id`.
- All scores reference the exact points used, returned via `include_evidence=true`.

No endpoint may emit:
- unstored facts
- invented narrative explanations
- numeric values not derivable from stored inputs

## Repository structure (target)
- `app/`
  - `api/`
    - `auth.py`
    - `routes_jobs.py`
    - `routes_countries.py`
    - `routes_industries.py`
    - `routes_companies.py`
  - `db/`
    - `models.py`
    - `session.py`
  - `migrations/`
  - `jobs/`
    - `registry.py`   (thread-safe in-memory cache + Postgres persistence)
    - `queue.py`      (global concurrency control)
    - `runner.py`     (runs job handlers; streams logs)
    - `handlers/`     (country/industry/company job handlers)
  - `ingest/`
    - `world_bank.py`
    - `fred.py`
    - `gdelt.py`
    - `sec_edgar.py`
    - `marketdata.py`
  - `score/`
    - `country.py`
    - `industry.py`
    - `company.py`
    - `versions.py`   (calc_version constants)
  - `packets/`
    - `country_packets.py`
    - `industry_packets.py`
    - `company_packets.py`
  - `scheduler/`
    - `daily.py`
  - `cli.py` (Typer)
- `config/`
  - `investable_countries_v1.json`
  - weights and rubrics JSON
- `scripts/`
  - `e2e_country.py` (v1)
- `tests/`

## Database tables (minimum set)
- `users`
- `subscriptions`
- `jobs`
- `data_sources`
- `artefacts`
- `countries`
- `country_series` / `country_series_points`
- `country_scores`
- `country_risk_register`
- `decision_packets`

Industry and company tables are added in later milestones.

## API endpoints (minimum set)
Auth is required for all except health checks.

- `GET /healthz` (no auth)
- `POST /api/jobs` (enqueue job; plan-gated)
- `GET /api/jobs/{id}` (status)
- `GET /api/jobs/{id}/stream` (SSE logs)
- `GET /v1/countries` (latest scores)
- `GET /v1/country/{iso2}/summary?as_of=YYYY-MM-01&include_evidence=true|false`
- `POST /v1/admin/refresh` (admin-only; triggers batch jobs)

Industry/company endpoints follow the same decision-packet pattern.

## Scheduling
- A daily scheduler enqueues per-user or global refresh jobs, depending on product design.
- For shared datasets (country/market), compute once and cache; per-user jobs reference shared artefacts/scores.
- For user-specific universes/watchlists, compute user-tailored packets by joining against shared data.

## Writing style
- Always use British spellings (e.g. standardise, colour, behaviour, centre, analyse, organisation, favour, licence, etc.)
- This applies to code comments, PRDs, commit messages, and all written output

## Implementation rules for Claude
- **PRD-first workflow**: Every plan must produce a PRD at `docs/product/prd_X_Y.md` **before** any code is written. The PRD documents: problem statement, solution design, data sources, API surface, data model changes, files changed, and acceptance criteria. Major milestones use `prd_X_0.md`; incremental features use `prd_X_Y.md`. The PRD is the source of truth — code implements what the PRD specifies.
- Implement one milestone at a time.
- After each milestone:
  - add tests
  - run `pytest -q`
  - run the relevant e2e script
- Prefer simple, explicit code over clever abstractions.
- When a spec is missing, create a TODO and stop that thread; do not invent semantics.

## Standard commands that must work
- `pytest -q`
- `alembic upgrade head`
- `python -m app.cli run daily`
- `python -m scripts.e2e_country`