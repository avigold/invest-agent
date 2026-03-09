import { useState, useMemo, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { useMLModels, useMLModelScores, queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";

const PAGE_SIZE = 25;

interface Score {
  id: string;
  ticker: string;
  company_name: string;
  country: string;
  sector: string;
  probability: number;
  suggested_weight: number;
  contributing_features: Record<string, unknown>;
  scored_at: string;
  deterministic_classification?: string;
}

interface ModelSummary {
  id: string;
  model_version: string;
  nickname: string | null;
  is_active: boolean;
  aggregate_metrics: { mean_auc?: number };
  created_at: string;
}

type SortKey = "rank" | "ticker" | "country" | "sector" | "probability";
type SortDir = "asc" | "desc";

function fmtPct(v: number | undefined | null, decimals = 1): string {
  return v != null ? `${(v * 100).toFixed(decimals)}%` : "\u2014";
}

function ShimmerCard() {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 px-4 py-3">
      <div className="h-3 w-16 animate-pulse rounded bg-gray-700/50" />
      <div className="mt-2 h-6 w-20 animate-pulse rounded bg-gray-700/50" />
      <div className="mt-1 h-3 w-24 animate-pulse rounded bg-gray-700/50" />
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 px-4 py-3">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className="mt-1 text-xl font-bold text-white">{value}</div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  );
}

export default function MLPicks() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [page, setPage] = useState(1);

  // Dependent queries: models → latest model → scores
  const { data: models = [], error: modelsError, isLoading: modelsLoading } = useMLModels<ModelSummary[]>();
  const latestModel = models.find((m) => m.is_active) ?? (models.length > 0 ? models[0] : null);
  const { data: scoresData, isLoading: scoresLoading } = useMLModelScores<{ items: Score[]; total: number }>(
    latestModel?.id || "",
  );

  const scores = scoresData?.items ?? [];
  const model = latestModel;

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  const handleFlush = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.mlModels() });
    if (latestModel) {
      queryClient.invalidateQueries({ queryKey: queryKeys.mlModelScores(latestModel.id) });
    }
  };

  const getCountry = (s: Score): string => {
    if (s.country) return s.country;
    const cf = s.contributing_features as Record<string, string | Record<string, unknown>>;
    return (cf?.country as string) || "";
  };

  const getSector = (s: Score): string => {
    if (s.sector) return s.sector;
    const cf = s.contributing_features as Record<string, string | Record<string, unknown>>;
    return (cf?.sector as string) || "";
  };

  const hasAll = scores.length > 0;

  // Country breakdown
  const countryBreakdown = useMemo(() => {
    const map: Record<string, { count: number; weight: number }> = {};
    for (const s of scores) {
      const c = getCountry(s) || "??";
      if (!map[c]) map[c] = { count: 0, weight: 0 };
      map[c].count++;
      map[c].weight += s.suggested_weight;
    }
    return Object.entries(map)
      .sort((a, b) => b[1].weight - a[1].weight)
      .slice(0, 10);
  }, [scores]);

  // Sorting
  const sorted = useMemo(() => {
    const arr = scores.map((s, i) => ({ ...s, rank: i + 1 }));
    if (sortKey === "rank") {
      return sortDir === "asc" ? arr : [...arr].reverse();
    }
    return [...arr].sort((a, b) => {
      let va: string | number, vb: string | number;
      switch (sortKey) {
        case "ticker": va = a.ticker; vb = b.ticker; break;
        case "country": va = getCountry(a); vb = getCountry(b); break;
        case "sector": va = getSector(a); vb = getSector(b); break;
        case "probability": va = a.probability; vb = b.probability; break;
        default: va = a.rank; vb = b.rank;
      }
      const cmp = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [scores, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "ticker" || key === "country" || key === "sector" ? "asc" : "desc");
    }
  };

  const sortIcon = (key: SortKey) => {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " \u25b2" : " \u25bc";
  };

  // Search filtering
  const q = search.toLowerCase();
  const filtered = q
    ? sorted.filter(
        (s) =>
          s.ticker.toLowerCase().includes(q) ||
          s.company_name.toLowerCase().includes(q),
      )
    : sorted;

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visible = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  // Reset page on search/sort change
  useEffect(() => {
    setPage(1);
  }, [search, sortKey, sortDir]);

  const initialLoading = modelsLoading;

  if (loading || !user) return null;
  if (!initialLoading && modelsError && scores.length === 0) {
    return (
      <div className="rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
        {(modelsError as Error).message}
      </div>
    );
  }

  const withWeights = scores.filter((s) => s.suggested_weight > 0);

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">
            ML Picks
            {hasAll && (
              <span className="ml-2 text-base font-normal text-gray-500">
                {q
                  ? `${filtered.length} of ${scores.length}`
                  : `${scores.length}`}
              </span>
            )}
          </h1>
          {model && (
            <p className="mt-1 text-sm text-gray-500">
              Model: <Link to={`/ml/models/${model.id}`} className="text-blue-400 hover:text-blue-300">
                {model.model_version}
              </Link>
              {" \u00b7 "}AUC {model.aggregate_metrics.mean_auc?.toFixed(3)}
              {" \u00b7 "}Scored {new Date(scores[0]?.scored_at ?? model.created_at).toLocaleDateString()}
            </p>
          )}
        </div>
        <button
          onClick={handleFlush}
          title="Clear cache and reload"
          className="rounded-lg border border-gray-700 bg-gray-800 p-2 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>

      {initialLoading ? (
        <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-12 flex items-center justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
          <span className="ml-3 text-sm text-gray-500">Loading scores...</span>
        </div>
      ) : scores.length === 0 ? (
        scoresLoading ? (
          <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-12 flex items-center justify-center">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
            <span className="ml-3 text-sm text-gray-500">Loading scores...</span>
          </div>
        ) : (
          <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-8 text-center">
            <p className="text-gray-400">No scores available yet.</p>
            <p className="mt-2 text-sm text-gray-600">
              Run <code className="rounded bg-gray-800 px-1.5 py-0.5 text-xs">python -m app.cli score-universe</code> to score the universe.
            </p>
          </div>
        )
      ) : (
        <>
          {/* Summary cards */}
          <div className="mb-6 grid gap-3 grid-cols-2 sm:grid-cols-4">
            {hasAll ? (
              <>
                <StatCard
                  label="Stocks Scored"
                  value={String(scores.length)}
                  sub={`${withWeights.length} in portfolio`}
                />
                <StatCard
                  label="Top Probability"
                  value={fmtPct(scores[0]?.probability)}
                  sub={scores[0]?.ticker}
                />
                <StatCard
                  label="Portfolio"
                  value="Top 50"
                  sub="2% each"
                />
                <StatCard
                  label="Countries"
                  value={String(countryBreakdown.length)}
                  sub={countryBreakdown.slice(0, 3).map(([c]) => c).join(", ")}
                />
              </>
            ) : (
              <>
                <ShimmerCard />
                <ShimmerCard />
                <ShimmerCard />
                <ShimmerCard />
              </>
            )}
          </div>

          {/* Country breakdown */}
          <div className="mb-6 rounded-xl border border-gray-800 bg-gray-900/80 p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
              Country Allocation
            </h2>
            {hasAll ? (
              <div className="flex flex-wrap gap-3">
                {countryBreakdown.map(([country, { count, weight }]) => (
                  <div key={country} className="flex items-center gap-2 text-sm">
                    <span className="font-mono text-white">{country}</span>
                    <span className="text-gray-500">{fmtPct(weight)}</span>
                    <span className="text-gray-600">({count})</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-wrap gap-3">
                {[1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="h-5 w-24 animate-pulse rounded bg-gray-700/50" />
                ))}
              </div>
            )}
          </div>

          {/* Search */}
          <div className="mb-4">
            <div className="relative w-full sm:w-64">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Name | Symbol"
                className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 pr-8 text-sm text-gray-300 placeholder-gray-500"
              />
            </div>
          </div>

          {/* Scores table */}
          <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-5">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                    <th className="px-3 py-2 cursor-pointer hover:text-gray-300" onClick={() => toggleSort("rank")}>
                      #{sortIcon("rank")}
                    </th>
                    <th className="px-3 py-2 cursor-pointer hover:text-gray-300" onClick={() => toggleSort("ticker")}>
                      Company{sortIcon("ticker")}
                    </th>
                    <th className="px-3 py-2 cursor-pointer hover:text-gray-300" onClick={() => toggleSort("country")}>
                      Country{sortIcon("country")}
                    </th>
                    <th className="px-3 py-2 cursor-pointer hover:text-gray-300" onClick={() => toggleSort("sector")}>
                      Sector{sortIcon("sector")}
                    </th>
                    <th className="px-3 py-2 text-right cursor-pointer hover:text-gray-300" onClick={() => toggleSort("probability")}>
                      Probability{sortIcon("probability")}
                    </th>
                    <th className="px-3 py-2 text-center">Portfolio</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((s) => (
                    <tr key={s.id} className="border-b border-gray-800/50 hover:bg-white/[0.015]">
                      <td className="px-3 py-2 font-mono text-gray-500">{s.rank}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5">
                          {s.deterministic_classification === "Buy" && (
                            <span className="group relative flex-shrink-0">
                              <svg className="h-4 w-4 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                                <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                              </svg>
                              <span className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 -translate-x-1/2 whitespace-nowrap rounded bg-gray-700 px-2 py-1 text-xs text-gray-200 opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                                Also recommended Buy by Fundamentals scoring
                              </span>
                            </span>
                          )}
                          <div>
                            <Link to={`/stocks/${s.ticker}`} className="font-medium text-white hover:text-blue-400">
                              {s.ticker}
                            </Link>
                            <div className="text-xs text-gray-500">{s.company_name}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2 font-mono text-gray-400">
                        {getCountry(s) || "\u2014"}
                      </td>
                      <td className="px-3 py-2 text-xs text-gray-400">
                        {getSector(s) || "\u2014"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-white">
                        {fmtPct(s.probability)}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {s.suggested_weight > 0 ? (
                          <span className="inline-block rounded-full bg-green-900/50 border border-green-800 px-2 py-0.5 text-xs text-green-300">
                            In Portfolio
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                  {visible.length === 0 && q && (
                    <tr>
                      <td colSpan={6} className="px-3 py-8 text-center text-gray-500">
                        No matches for &ldquo;{search}&rdquo;
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between text-sm">
              <span className="text-gray-500">
                {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} of {filtered.length}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage(safePage - 1)}
                  disabled={safePage <= 1}
                  className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Prev
                </button>
                <span className="text-gray-400">
                  Page {safePage} of {totalPages}
                </span>
                <button
                  onClick={() => setPage(safePage + 1)}
                  disabled={safePage >= totalPages}
                  className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
