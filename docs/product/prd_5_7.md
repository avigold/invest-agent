# PRD 5.7 — Recommendation Detail View

**Product**: investagent.app
**Version**: 5.7 (incremental, builds on PRD 5.5)
**Date**: 2026-03-01
**Status**: Complete
**Milestone**: 5

---

## 1. What this PRD covers

Add a dedicated recommendation detail page at `/recommendations/{ticker}` that shows the full composite scoring breakdown (country, industry, company), links to each scoring layer's detail view, and an AI-generated analysis explaining the recommendation rationale.

## 2. Problem statement

Clicking a company in the recommendations table currently navigates to the company detail page, which only shows company-level scores. The country and industry context that drove the recommendation is lost. Users must manually navigate to three separate pages to understand the full picture behind a Buy/Hold/Sell signal.

## 3. Solution overview

### 3.1 New API endpoint

`GET /v1/recommendation/{ticker}`

Assembles the complete recommendation context for a single company:

Response shape:
```json
{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "classification": "Buy",
  "composite_score": 74.2,
  "rank": 1,
  "rank_total": 25,
  "as_of": "2026-02-01",
  "recommendation_version": "recommendation_v2",
  "scores": {
    "company": { "score": 78.5, "weight": 0.60 },
    "country": { "score": 65.3, "weight": 0.20 },
    "industry": { "score": 71.0, "weight": 0.20 }
  },
  "country": {
    "iso2": "US",
    "name": "United States",
    "overall_score": 65.3
  },
  "industry": {
    "gics_code": "45",
    "name": "Information Technology",
    "country_iso2": "US",
    "overall_score": 71.0
  },
  "company": {
    "ticker": "AAPL",
    "name": "Apple Inc.",
    "overall_score": 78.5
  },
  "packets": {
    "country": { ... },
    "industry": { ... },
    "company": { ... }
  },
  "analysis": {
    "summary": "...",
    "country_assessment": "...",
    "industry_assessment": "...",
    "company_assessment": "...",
    "risks_and_catalysts": "...",
    "model_id": "claude-sonnet-4-5-20241022",
    "analysis_version": "analysis_v1"
  }
}
```

### 3.2 AI analysis module

MCP-tool-like design:
- Structured input (recommendation dict + decision packet summaries) → structured output (5 text sections)
- `temperature=0` for maximum determinism
- Pinned model: `claude-sonnet-4-5-20241022`
- Cache by SHA-256 hash of canonical score JSON + prompt template hash
- Stored in `recommendation_analyses` DB table
- Graceful fallback: returns `null` analysis if API key is missing

### 3.2.1 Job-based generation

Analysis is **not** generated synchronously on page load. Instead:
- User clicks "Generate Analysis" button on the recommendation detail page
- This creates a `recommendation_analysis` job with `params: { ticker }`
- The job handler computes recommendations, fetches packets, and calls the Claude API
- On completion, the analysis is cached in the `recommendation_analyses` table
- The page polls the job status and refreshes when done
- Other users who view the same recommendation see the cached analysis immediately, as long as scores haven't changed (cache is keyed by `score_hash`)

### 3.3 Frontend page

`/recommendations/:ticker` detail page:
- Header with company name, ticker, classification badge, rank
- Large composite score with weighted breakdown visualization
- Three score cards (Country, Industry, Company) with "View details" links
- AI analysis sections rendered as formatted text
- Metadata footer with version info

## 4. Database changes

New table `recommendation_analyses`:
- `id` UUID PK
- `ticker` VARCHAR(20) NOT NULL
- `score_hash` VARCHAR(64) NOT NULL — SHA-256 of canonical score JSON
- `prompt_hash` VARCHAR(64) NOT NULL — SHA-256 of prompt template
- `analysis_version` VARCHAR(50) NOT NULL
- `model_id` VARCHAR(100) NOT NULL
- `content` JSONB NOT NULL — structured analysis sections
- `created_at` TIMESTAMPTZ NOT NULL
- Unique constraint on `(ticker, score_hash, prompt_hash)`

## 5. Files changed

| File | Action |
|---|---|
| `app/config.py` | Modify — add `anthropic_api_key` field |
| `app/db/models.py` | Modify — add `RecommendationAnalysis` model |
| `alembic/versions/xxx_add_recommendation_analyses.py` | New — migration |
| `app/analysis/__init__.py` | New — empty init |
| `app/analysis/recommendation_analysis.py` | New — analysis generation + caching |
| `app/jobs/handlers/recommendation.py` | New — job handler for analysis generation |
| `app/jobs/handlers/__init__.py` | Modify — register handler |
| `app/jobs/schemas.py` | Modify — add RECOMMENDATION_ANALYSIS enum |
| `app/api/routes_jobs.py` | Modify — add free plan limit |
| `app/api/routes_recommendations.py` | Modify — add detail endpoint (cache-only analysis) |
| `web/src/App.tsx` | Modify — add route |
| `web/src/pages/RecommendationDetail.tsx` | New — detail page |
| `web/src/components/RecommendationTable.tsx` | Modify — update links |
| `web/src/pages/Dashboard.tsx` | Modify — update top buys links |

## 6. Acceptance criteria

- [ ] `GET /v1/recommendation/{ticker}` returns full composite context
- [ ] Unknown ticker returns 404
- [ ] "Generate Analysis" button triggers `recommendation_analysis` job
- [ ] AI analysis generated with temperature=0, pinned model
- [ ] Analysis cached by score_hash — same scores return cached analysis
- [ ] Analysis gracefully null when ANTHROPIC_API_KEY is missing
- [ ] Other users see cached analysis without re-generating
- [ ] Frontend page renders at `/recommendations/{ticker}`
- [ ] Composite score breakdown shows weighted contributions
- [ ] Three score cards link to country, industry, company detail pages
- [ ] AI analysis sections render as formatted text
- [ ] Recommendation table links updated to point to recommendation detail
- [ ] Dashboard top buys links updated to point to recommendation detail
- [ ] All existing tests continue to pass
- [ ] TypeScript clean, build succeeds

## 7. Determinism strategy

- **temperature=0**: Minimizes output variation across identical inputs
- **Canonical JSON**: `json.dumps(scores, sort_keys=True)` ensures consistent hash inputs
- **score_hash**: SHA-256 of all input scores — cache key for when scores haven't changed
- **prompt_hash**: SHA-256 of prompt template — invalidates cache when prompt changes
- **analysis_version**: Coarse version string for manual cache-busting
- **Model pinning**: Dated model ID constant prevents drift from model updates
