import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson, apiFetch } from "@/lib/api";

// ── Query keys ──────────────────────────────────────────────────────────

export const queryKeys = {
  countries: () => ["countries"] as const,
  country: (iso2: string) => ["country", iso2] as const,
  industries: (iso2?: string) => ["industries", { iso2 }] as const,
  industry: (gics_code: string, iso2: string) => ["industry", gics_code, iso2] as const,
  companies: (filters: { gics_code?: string; country_iso2?: string }) => ["companies", filters] as const,
  company: (ticker: string) => ["company", ticker] as const,
  recommendations: (filters: Record<string, string | undefined>) => ["recommendations", filters] as const,
  recommendation: (ticker: string) => ["recommendation", ticker] as const,
  mlModels: () => ["mlModels"] as const,
  mlModel: (id: string) => ["mlModel", id] as const,
  mlModelScores: (id: string) => ["mlModelScores", id] as const,
  mlStock: (ticker: string) => ["mlStock", ticker] as const,
  mlLatestScores: (limit?: number) => ["mlLatestScores", { limit }] as const,
  jobs: () => ["jobs"] as const,
  job: (id: string) => ["job", id] as const,
  screenerResults: () => ["screenerResults"] as const,
  screenerResult: (id: string) => ["screenerResult", id] as const,
  screenFields: () => ["screenFields"] as const,
  savedScreens: () => ["savedScreens"] as const,
  chart: (ticker: string, period: string, benchmark?: string) => ["chart", ticker, period, benchmark ?? null] as const,
  scoringProfiles: () => ["scoringProfiles"] as const,
  scoringDefaults: () => ["scoringDefaults"] as const,
  adminStats: () => ["admin", "stats"] as const,
  adminUsers: () => ["admin", "users"] as const,
  adminJobs: () => ["admin", "jobs"] as const,
  dashboardJobs: () => ["dashboardJobs"] as const,
  dashboardCountries: () => ["dashboardCountries"] as const,
  dashboardCompanies: () => ["dashboardCompanies"] as const,
  dashboardIndustries: () => ["dashboardIndustries"] as const,
  watchlist: () => ["watchlist"] as const,
  watchlistCheck: (ticker: string) => ["watchlistCheck", ticker] as const,
  signalChanges: () => ["signalChanges"] as const,
  peerValuation: (ticker: string) => ["peerValuation", ticker] as const,
} as const;

// ── Detail hooks (Phase 1) ──────────────────────────────────────────────

export function useCountryDetail<T = unknown>(iso2: string) {
  return useQuery<T>({
    queryKey: queryKeys.country(iso2),
    queryFn: () => apiJson<T>(`/v1/country/${iso2}/summary?include_evidence=true`),
    enabled: !!iso2,
  });
}

export function useCompanyDetail<T = unknown>(ticker: string) {
  return useQuery<T>({
    queryKey: queryKeys.company(ticker),
    queryFn: () => apiJson<T>(`/v1/company/${ticker}/summary?include_evidence=true`),
    enabled: !!ticker,
    retry: false,
  });
}

export function useIndustryDetail<T = unknown>(gics_code: string, iso2: string) {
  return useQuery<T>({
    queryKey: queryKeys.industry(gics_code, iso2),
    queryFn: () => apiJson<T>(`/v1/industry/${gics_code}/summary?iso2=${iso2}`),
    enabled: !!gics_code,
  });
}

export function useMLStockDetail<T = unknown>(ticker: string) {
  return useQuery<T>({
    queryKey: queryKeys.mlStock(ticker),
    queryFn: () => apiJson<T>(`/v1/predictions/score/${ticker.replace(/\./g, "-")}`),
    enabled: !!ticker,
    retry: false,
  });
}

export function useMLModel<T = unknown>(id: string) {
  return useQuery<T>({
    queryKey: queryKeys.mlModel(id),
    queryFn: () => apiJson<T>(`/v1/predictions/models/${id}`),
    enabled: !!id,
  });
}

export function useMLModelScores<T = { items: unknown[]; total: number }>(id: string) {
  return useQuery<T>({
    queryKey: queryKeys.mlModelScores(id),
    queryFn: () => apiJson<T>(`/v1/predictions/models/${id}/scores`),
    enabled: !!id,
  });
}

export function useMLModels<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.mlModels(),
    queryFn: () => apiJson<T>("/v1/predictions/models"),
  });
}

export function useScreenerResults<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.screenerResults(),
    queryFn: () => apiJson<T>("/v1/screener/results"),
  });
}

// ── Polling hooks (Phase 2) ─────────────────────────────────────────────

export function useJobs<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.jobs(),
    queryFn: () => apiJson<T>("/api/jobs"),
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data as Array<{ status: string }> | undefined;
      const hasActive = data?.some((j) => j.status === "running" || j.status === "queued");
      return hasActive ? 3000 : false;
    },
  });
}

export function useJobDetail<T = unknown>(id: string) {
  return useQuery<T>({
    queryKey: queryKeys.job(id),
    queryFn: () => apiJson<T>(`/api/jobs/${id}`),
    enabled: !!id,
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data as { status: string } | undefined;
      return data?.status === "running" || data?.status === "queued" ? 3000 : false;
    },
  });
}

export function useJobLogs(jobId: string, status: string) {
  return useQuery<{ log_text: string | null; status: string }>({
    queryKey: queryKeys.job(jobId),
    queryFn: () => apiJson<{ log_text: string | null; status: string }>(`/api/jobs/${jobId}`),
    enabled: !!jobId && status !== "queued",
    staleTime: 0,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.status === "running" ? 1000 : false;
    },
  });
}

// ── Dashboard hooks (Phase 3) ─────────────────────────────────────────

export function useDashboardJobs<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.dashboardJobs(),
    queryFn: () => apiJson<T>("/api/jobs"),
  });
}

export function useDashboardCountries<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.dashboardCountries(),
    queryFn: () => apiJson<T>("/v1/countries"),
  });
}

export function useDashboardCompanies<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.dashboardCompanies(),
    queryFn: () => apiJson<T>("/v1/companies?limit=5"),
  });
}

export function useDashboardIndustries<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.dashboardIndustries(),
    queryFn: () => apiJson<T>("/v1/industries?limit=5"),
  });
}

export function useMLLatestScores<T = unknown>() {
  return useQuery<T>({
    queryKey: queryKeys.mlLatestScores(10),
    queryFn: () => apiJson<T>("/v1/predictions/models/latest/scores?limit=10"),
  });
}

// ── List hooks (Phase 4) ──────────────────────────────────────────────

export function useCountries<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.countries(),
    queryFn: () => apiJson<T>("/v1/countries"),
  });
}

export function useIndustries<T = unknown[]>(iso2?: string) {
  return useQuery<T>({
    queryKey: queryKeys.industries(iso2),
    queryFn: () => {
      const params = iso2 ? `?iso2=${iso2}` : "";
      return apiJson<T>(`/v1/industries${params}`);
    },
  });
}

export function useCompanies<T = unknown[]>(filters: {
  gics_code?: string;
  country_iso2?: string;
}) {
  return useQuery<T>({
    queryKey: queryKeys.companies(filters),
    queryFn: () => {
      const params = new URLSearchParams();
      if (filters.gics_code) params.set("gics_code", filters.gics_code);
      if (filters.country_iso2) params.set("country_iso2", filters.country_iso2);
      const qs = params.toString();
      return apiJson<T>(`/v1/companies${qs ? `?${qs}` : ""}`);
    },
  });
}

export function useRecommendations<T = unknown[]>(filters: Record<string, string | undefined>) {
  return useQuery<T>({
    queryKey: queryKeys.recommendations(filters),
    queryFn: () => {
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) {
        if (v) params.set(k, v);
      }
      const qs = params.toString();
      return apiJson<T>(`/v1/recommendations${qs ? `?${qs}` : ""}`);
    },
  });
}

export function useScoringProfiles<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.scoringProfiles(),
    queryFn: () => apiJson<T>("/v1/scoring-profiles"),
  });
}

// ── Phase 5 hooks ───────────────────────────────────────────────────────

export function useAdminStats<T = unknown>() {
  return useQuery<T>({
    queryKey: queryKeys.adminStats(),
    queryFn: () => apiJson<T>("/api/admin/stats"),
  });
}

export function useAdminUsers<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.adminUsers(),
    queryFn: () => apiJson<T>("/api/admin/users"),
  });
}

export function useAdminJobs<T = unknown[]>() {
  return useQuery<T>({
    queryKey: queryKeys.adminJobs(),
    queryFn: () => apiJson<T>("/api/admin/jobs"),
  });
}

export function useRecommendationDetail<T = unknown>(ticker: string) {
  return useQuery<T>({
    queryKey: queryKeys.recommendation(ticker),
    queryFn: () => apiJson<T>(`/v1/recommendation/${ticker}`),
    enabled: !!ticker,
  });
}

// ── Live screener hooks ──────────────────────────────────────────────────

export function useScreenFields<T = unknown>() {
  return useQuery<T>({
    queryKey: queryKeys.screenFields(),
    queryFn: () => apiJson<T>("/v1/screener/live/fields"),
    staleTime: 300_000,
  });
}

export function useSavedScreens<T = unknown>() {
  return useQuery<T>({
    queryKey: queryKeys.savedScreens(),
    queryFn: () => apiJson<T>("/v1/screener/saved"),
  });
}

export function useSaveScreen() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; filters: unknown; sort_by?: string; sort_desc?: boolean }) =>
      apiJson("/v1/screener/saved", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.savedScreens() });
    },
  });
}

export function useUpdateSavedScreen() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { id: string; name: string; filters: unknown; sort_by?: string; sort_desc?: boolean }) =>
      apiJson(`/v1/screener/saved/${data.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.savedScreens() });
    },
  });
}

export function useDeleteSavedScreen() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/v1/screener/saved/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.savedScreens() });
    },
  });
}

export function useScreenerResultDetail<T = unknown>(id: string) {
  return useQuery<T>({
    queryKey: queryKeys.screenerResult(id),
    queryFn: () => apiJson<T>(`/v1/screener/results/${id}`),
    enabled: !!id,
  });
}

export function useChartData<T = unknown>(ticker: string, period: string, benchmark?: string) {
  return useQuery<T>({
    queryKey: queryKeys.chart(ticker, period, benchmark),
    queryFn: () => {
      const params = new URLSearchParams({ period });
      if (benchmark) params.set("benchmark", benchmark);
      return apiJson<T>(
        `/v1/company/${ticker.replace(/\./g, "-")}/chart?${params.toString()}`,
      );
    },
    enabled: !!ticker,
    staleTime: 60_000,
    refetchInterval: (query) => {
      const d = query.state.data as
        | { market_status?: { is_open?: boolean } }
        | undefined;
      return d?.market_status?.is_open ? 60_000 : false;
    },
  });
}

// ── Watchlist hooks ─────────────────────────────────────────────────────

export interface WatchlistItem {
  id: string;
  ticker: string;
  name: string;
  country_iso2: string;
  gics_code: string;
  position: number;
  added_at: string;
  currency: string;
  overall_score: number | null;
  composite_score: number | null;
  fundamental_score: number | null;
  market_score: number | null;
  latest_price: number | null;
  change_1d: number | null;
  change_1d_pct: number | null;
  price_date: string | null;
}

export function useWatchlist() {
  return useQuery<WatchlistItem[]>({
    queryKey: queryKeys.watchlist(),
    queryFn: () => apiJson<WatchlistItem[]>("/v1/watchlist"),
  });
}

export function useWatchlistCheck(ticker: string) {
  return useQuery<{ in_watchlist: boolean }>({
    queryKey: queryKeys.watchlistCheck(ticker),
    queryFn: () => apiJson<{ in_watchlist: boolean }>(`/v1/watchlist/check/${ticker}`),
    enabled: !!ticker,
  });
}

export function useAddToWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) =>
      apiJson("/v1/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker }),
      }),
    onSuccess: (_data, ticker) => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist() });
      qc.invalidateQueries({ queryKey: queryKeys.watchlistCheck(ticker) });
    },
  });
}

export function useRemoveFromWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) =>
      apiFetch(`/v1/watchlist/${ticker}`, { method: "DELETE" }),
    onSuccess: (_data, ticker) => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist() });
      qc.invalidateQueries({ queryKey: queryKeys.watchlistCheck(ticker) });
    },
  });
}

export function useReorderWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (order: string[]) =>
      apiJson("/v1/watchlist/reorder", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist() });
    },
  });
}

export interface BulkAddResult {
  added: number;
  skipped: number;
  tickers_added: string[];
}

export function useBulkAddToWatchlist() {
  const qc = useQueryClient();
  return useMutation<BulkAddResult, Error, string[]>({
    mutationFn: (tickers: string[]) =>
      apiJson<BulkAddResult>("/v1/watchlist/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tickers }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist() });
      qc.invalidateQueries({ queryKey: ["watchlistCheck"] });
    },
  });
}

// ── Signal changes hooks ────────────────────────────────────────────────

export interface SignalChangeItem {
  id: string;
  ticker: string;
  company_name: string;
  system: string;
  old_classification: string;
  new_classification: string;
  old_score: number;
  new_score: number;
  detected_at: string;
}

export function useSignalChanges() {
  return useQuery<SignalChangeItem[]>({
    queryKey: queryKeys.signalChanges(),
    queryFn: () => apiJson<SignalChangeItem[]>("/v1/signals/changes?limit=10"),
    staleTime: 60_000,
  });
}

// ── Peer Valuation ────────────────────────────────────────────────────

export interface PeerMetricStats {
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
}

export interface PeerMetric {
  key: string;
  label: string;
  format: "multiple" | "pct";
  higher_is_better: boolean;
  company_value: number | null;
  percentile_rank: number | null;
  stats: PeerMetricStats;
}

export interface PeerValuationData {
  ticker: string;
  sector: string;
  gics_code: string;
  company_count: number;
  metrics: PeerMetric[];
}

export function usePeerValuation(ticker: string) {
  return useQuery<PeerValuationData>({
    queryKey: queryKeys.peerValuation(ticker),
    queryFn: () =>
      apiJson<PeerValuationData>(
        `/v1/company/${ticker.replace(/\./g, "-")}/peer-valuation`,
      ),
    enabled: !!ticker,
    retry: false,
    staleTime: 300_000,
  });
}
