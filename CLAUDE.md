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

## Implementation rules for Claude
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