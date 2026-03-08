# PRD 9.5 — Migrate to TanStack Query

## Problem Statement

All 17 data-fetching pages use manual `useState` + `useEffect` + `apiJson` patterns. React 18's StrictMode double-fires effects in development, causing duplicate API calls on every page load (confirmed via network inspection). The manual sessionStorage cache (`lib/cache.ts`) adds complexity with `flushKey`, `fetchId`, `firstPage`/`allScores` two-phase loading, and `readCache`/`writeCache` boilerplate across 5 pages.

## Solution

Replace all manual data fetching with TanStack Query (`@tanstack/react-query`), which provides:
- Automatic request deduplication (fixes StrictMode duplicate calls)
- In-memory cache with configurable staleness (replaces sessionStorage)
- Built-in loading/error states (eliminates manual `useState` pairs)
- Conditional polling via `refetchInterval` (replaces manual `setInterval`)
- Cache invalidation (replaces `flushKey` + `clearCache`)

## Design Decisions

1. **Two-phase loading → single query.** The `?limit=25` first-page fetch + unlimited background fetch compensated for having no cache. TanStack's in-memory cache makes return visits instant, so a single full-dataset query suffices.

2. **Custom hooks in `lib/queries.ts`.** Centralised query keys and typed hooks. Reusable across pages (e.g., Dashboard and Countries both fetch `/v1/countries`).

3. **Defaults:** `staleTime: 10 min` (matches current TTL), `gcTime: 30 min`, `retry: false`, `refetchOnWindowFocus: false`.

4. **Cache flush buttons → `queryClient.invalidateQueries()`.** No `flushKey` state needed.

5. **No backend changes.** All existing endpoints and response shapes stay as-is.

## New Files

| File | Purpose |
|------|---------|
| `web/src/lib/queryClient.ts` | QueryClient with defaults |
| `web/src/lib/queries.ts` | Query keys + custom hooks |

## Files Modified

| File | Change |
|------|--------|
| `web/src/main.tsx` | Add `QueryClientProvider` wrapper |
| 17 pages in `web/src/pages/` | Replace useEffect → useQuery/useMutation |
| 4 components in `web/src/components/` | Replace useEffect/setInterval → useQuery/useMutation |

## Files Deleted

| File | Reason |
|------|--------|
| `web/src/lib/cache.ts` | Fully replaced by TanStack Query's in-memory cache |

## Migration Order

0. **Infrastructure** — install dependency, create queryClient + queries module, update main.tsx
1. **Simple detail pages** — CountryDetail, CompanyDetail, IndustryDetail, MLStockDetail, PredictionDetail, Screener, Predictions
2. **Polling pages** — JobDetail, Jobs, LogViewer
3. **Dashboard** — 5 parallel queries with shared cache
4. **Complex list pages** — Countries, Industries, Companies, Recommendations, MLPicks
5. **Remaining components** — StockChart, ScoringProfileModal, JobsTable, RecommendationDetail, ScreenerResult, AddCompanies, Admin
6. **Cleanup** — delete cache.ts, remove all manual cache/state boilerplate

## Acceptance Criteria

- [ ] `npm run build` succeeds with no type errors
- [ ] `pytest -q` passes (no backend changes)
- [ ] MLPicks loads without duplicate API calls in dev (StrictMode)
- [ ] Navigating Dashboard → Countries → back to Dashboard shows cached data instantly
- [ ] Cache flush button on Countries/MLPicks/etc. triggers refetch
- [ ] Job polling starts when job is running, stops when done
- [ ] StockChart polls when market is open, stops when closed
- [ ] No references to `readCache`, `writeCache`, `clearCache`, or `lib/cache` remain
