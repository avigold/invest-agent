# PRD 9.6 — Unified Stock Detail Page

**Status**: Complete
## Problem

Three separate detail pages exist for the same stock:
- **CompanyDetail** (`/companies/:ticker`) — deterministic scores from decision packet. Hard 404s when no packet exists.
- **MLStockDetail** (`/ml/picks/:ticker`) — ML probability + 186 features. Hard 404s when no ML score exists.
- **RecommendationDetail** (`/fundamentals/:ticker`) — composite recommendation (kept separate).

Companies added via `score-universe` (ML) may not have decision packets (built by `company_refresh`), and vice versa. Users hitting `/companies/DFPH` see "No decision packet found" even though the company exists with ML data. The pages share the same stock chart and overlap significantly.

## Solution

Merge CompanyDetail and MLStockDetail into a single `/stocks/:ticker` page that fetches both data sources in parallel and gracefully shows whatever is available.

### URL scheme
- New canonical URL: `/stocks/:ticker`
- Old URLs redirect: `/companies/:ticker` → `/stocks/:ticker`, `/ml/picks/:ticker` → `/stocks/:ticker`
- RecommendationDetail stays at `/fundamentals/:ticker` (different view — composite recommendation)

### Data fetching
- Two parallel queries: `useCompanyDetail` + `useMLStockDetail` (existing hooks)
- Each can fail independently — page renders whatever succeeds
- Error only if BOTH fail

### Page layout
1. **Header**: company name, ticker, badges (In Portfolio, Both Agree)
2. **Stock chart** (unchanged)
3. **ML Score section** (if ML data exists): probability bar, top contributing features
4. **Deterministic Scores section** (if packet exists): score cards, risks
5. **Fundamentals Data** (if packet exists): ratios + market metrics
6. **All Features** (if ML data exists): collapsible categorised 186-feature sections
7. **Evidence Chain** (if packet has evidence)
8. **Metadata footer**

### Back link
- `navigate(-1)` — returns to wherever user came from

## No backend changes

Both existing endpoints stay as-is.

## Files Modified

| File | Change |
|------|--------|
| `web/src/pages/CompanyDetail.tsx` | Rewrite → unified `StockDetail` |
| `web/src/App.tsx` | Add `/stocks/:ticker`, redirect old paths |
| `web/src/components/CompanyTable.tsx` | Links → `/stocks/{ticker}` |
| `web/src/pages/MLPicks.tsx` | Links → `/stocks/{ticker}` |
| `web/src/pages/RecommendationDetail.tsx` | Company card link → `/stocks/{ticker}` |
| `web/src/components/RecommendationTable.tsx` | Update links if present |
| `web/src/pages/Dashboard.tsx` | Update links if present |

## Files Deleted

| File | Reason |
|------|--------|
| `web/src/pages/MLStockDetail.tsx` | Merged into StockDetail |

## Acceptance Criteria

- `/stocks/AAPL` shows both ML and deterministic sections
- `/stocks/DFPH` shows ML section only (no 404)
- `/companies/AAPL` redirects to `/stocks/AAPL`
- `/ml/picks/AAPL` redirects to `/stocks/AAPL`
- All list pages link to `/stocks/:ticker`
- Back button returns to the correct list page
- `npm run build` succeeds with no type errors
