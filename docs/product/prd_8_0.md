# PRD 8.0 — Unified Data Loading, Caching & Cache Flush

**Product**: investagent.app
**Version**: 8.0 (major)
**Date**: 2026-03-07
**Status**: Complete
**Milestone**: 8

---

## 1. What this PRD covers

Standardise all 5 list pages (Companies, ML Picks, Fundamentals, Countries, Industries) on a single loading, caching, search, and cache flush pattern using sessionStorage with TTL.

## 2. Problem statement

The app's 5 list pages have inconsistent loading patterns:
- Companies has two-phase loading with sessionStorage caching (no TTL)
- ML Picks and Fundamentals have basic sessionStorage caching (no TTL)
- Countries and Industries have no caching at all
- None have cache expiry — stale data persists for the entire browser session
- No mechanism for users to force-refresh stale data without submitting a backend job

This creates an inconsistent UX and means users can see stale data indefinitely.

## 3. Solution overview

### 3.1 Unified loading behaviour (all 5 pages)

On page visit:
1. **Lazy loading begins** — all items start loading, chunked into pages
2. **Loader shows** — a full-page spinner is visible until page one is ready
3. **Loader disappears** — as soon as the first page of results arrives, the spinner hides and the first page renders
4. **Background loading continues** — remaining data loads in the background

For Companies, the API supports `?limit=25` for a fast first page. For other pages where the API returns all results at once, "page one ready" equals "all data ready" — the spinner hides when the fetch completes.

### 3.2 Search behaviour (Companies, ML Picks, Fundamentals)

1. **Upon search term entry**, a separate search spinner appears inside the search input
2. **Search requires the background lazy load to have completed** — the spinner persists until all data is available
3. **Upon completion**, search filters and displays the results instantly
4. Condition: `q && !hasAll` shows the search spinner

Countries and Industries do not have search inputs today. This can be added later if needed.

### 3.3 Caching with TTL

Cache results in sessionStorage with reasonable expiry:
- **TTL**: 10 minutes
- **On revisit with valid cache**: render instantly, no loader flash
- **On revisit with expired cache**: show loader, re-fetch
- **Stale-while-revalidate**: even on cache hit, always fetch fresh data in the background and update the cache silently

### 3.4 Cache flush mechanism

Each page gets a small circular-arrow icon button in the header area. On click:
1. Clears that page's cache keys (prefix-based)
2. Resets data state to null (triggers loader)
3. Re-fetches from the API

This is distinct from the existing "Refresh Companies" / "Refresh Countries" / "Refresh Industries" buttons which submit backend compute jobs. The cache flush button only clears the browser-side cache and re-reads from the API.

### 3.5 Shared cache utility (`web/src/lib/cache.ts`)

New file. Extracts duplicated cache logic into a shared module:

```typescript
export const CACHE_TTL = 10 * 60 * 1000; // 10 minutes

readCache<T>(key, ttl?)  // Returns null if missing/expired. Default TTL: 10 min.
writeCache<T>(key, data) // Stores {data, timestamp} in sessionStorage.
clearCache(prefix?)      // Clears keys by prefix, or all.
```

Storage format: `{ data: T, timestamp: number }`

### 3.6 Cache key prefixes

| Page | Prefix | Key Pattern |
|------|--------|-------------|
| Companies | `companies:` | `companies:${sector}:${country}` |
| ML Picks | `mlpicks:` | `mlpicks:scores`, `mlpicks:model` |
| Fundamentals | `recommendations:` | `recommendations:${cls}:${country}:${sector}:${profile}` |
| Countries | `countries:` | `countries:data` |
| Industries | `industries:` | `industries:${country}` |

### 3.7 Loading states summary

| State | Trigger | UI |
|-------|---------|-----|
| Initial load (no cache) | `data === null` | Full-page spinner centred in table/card area |
| Search pending | `q && !hasAll` | Small spinner inside search input (right side) |
| Background refresh | Cache hit, re-fetching | No visible indicator (silent update) |
| Cache flush clicked | Manual flush | Full-page spinner (same as initial load) |

## 4. Current state of each page

### Companies (`web/src/pages/Companies.tsx`)
- Has inline `cacheKey()`, `readCache()`, `writeCache()` — no TTL
- Has two-phase loading (firstPage fast via `?limit=25`, allCompanies background)
- Has search spinner: `{q && !hasAll && (spinner)}`
- **Changes**: Replace 3 inline cache functions with shared imports, add flush button

### ML Picks (`web/src/pages/MLPicks.tsx`)
- Has inline `readCache<T>()`, `writeCache()` — no TTL
- Cache keys: `mlpicks:scores`, `mlpicks:model`
- Has search spinner: `{q && fetching && (spinner)}`
- **Changes**: Replace 2 inline cache functions with shared imports, add flush button

### Fundamentals (`web/src/pages/Recommendations.tsx`)
- Has inline `recCacheKey()`, `readCache<T>()`, `writeCache()` — no TTL
- **Changes**: Replace 3 inline cache functions with shared imports, add flush button

### Countries (`web/src/pages/Countries.tsx`)
- No caching at all; simple `apiJson` fetch with `fetching` boolean
- Initial state: `useState<CountryRow[]>([])` (empty array, not null)
- **Changes**: Add caching with shared utility, change initial state to null for proper loader detection, add flush button

### Industries (`web/src/pages/Industries.tsx`)
- No caching at all; simple `apiJson` fetch with `fetching` boolean
- Initial state: `useState<IndustryRow[]>([])` (empty array, not null)
- **Changes**: Add caching with shared utility, change initial state to null for proper loader detection, add flush button

## 5. Files changed

| File | Action |
|------|--------|
| `web/src/lib/cache.ts` | New — shared cache utility with TTL |
| `web/src/pages/Companies.tsx` | Modify — replace 3 inline cache functions with shared imports, add flush button |
| `web/src/pages/MLPicks.tsx` | Modify — replace 2 inline cache functions with shared imports, add flush button |
| `web/src/pages/Recommendations.tsx` | Modify — replace 3 inline cache functions with shared imports, add flush button |
| `web/src/pages/Countries.tsx` | Modify — add caching (readCache/writeCache), null initial state, flush button |
| `web/src/pages/Industries.tsx` | Modify — add caching (readCache/writeCache), null initial state, flush button |

## 6. Acceptance criteria

- [ ] All 5 list pages use `readCache`/`writeCache` from `web/src/lib/cache.ts`
- [ ] On page visit, a loader shows until the first page of results is ready
- [ ] Cached data renders instantly on revisit (no loader flash)
- [ ] Cache expires after 10 minutes — revisit after expiry shows loader
- [ ] Background re-fetch updates cache silently without visual disruption
- [ ] Search spinner appears inside the search input when user has typed AND full data isn't loaded yet
- [ ] Search results display instantly once background load completes
- [ ] Each page has a visible cache flush button that clears cache and re-fetches
- [ ] Cache flush button is visually distinct from existing job-submit "Refresh" buttons
- [ ] No inline `readCache`/`writeCache` functions remain in page files
- [ ] TypeScript clean, build succeeds
