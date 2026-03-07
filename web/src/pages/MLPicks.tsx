import { useEffect, useState, useMemo, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { readCache, writeCache, clearCache } from "@/lib/cache";

const PAGE_SIZE = 25;

interface Score {
  id: string;
  ticker: string;
  company_name: string;
  country: string;
  sector: string;
  probability: number;
  confidence_tier: string;
  kelly_fraction: number;
  suggested_weight: number;
  contributing_features: Record<string, unknown>;
  scored_at: string;
}

interface ModelSummary {
  id: string;
  model_version: string;
  aggregate_metrics: { mean_auc?: number };
  created_at: string;
}

type SortKey = "rank" | "ticker" | "country" | "sector" | "probability" | "kelly" | "weight";
type SortDir = "asc" | "desc";

function fmtPct(v: number | undefined | null, decimals = 1): string {
  return v != null ? `${(v * 100).toFixed(decimals)}%` : "\u2014";
}

const TIER_COLORS: Record<string, string> = {
  high: "bg-green-900/50 text-green-300 border-green-800",
  medium: "bg-yellow-900/50 text-yellow-300 border-yellow-800",
  low: "bg-gray-800 text-gray-300 border-gray-700",
  negligible: "bg-gray-900 text-gray-500 border-gray-800",
};

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
  // First page (fast initial load when no cache)
  const [firstPage, setFirstPage] = useState<Score[] | null>(null);
  // Full dataset (from cache or background fetch)
  const [allScores, setAllScores] = useState<Score[] | null>(null);
  const [model, setModel] = useState<ModelSummary | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [page, setPage] = useState(1);
  const [flushKey, setFlushKey] = useState(0);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  useEffect(() => {
    if (!user) return;

    // Try cache first
    const cachedScores = readCache<Score[]>("mlpicks:scores");
    const cachedModel = readCache<ModelSummary>("mlpicks:model");
    if (cachedScores && cachedModel) {
      setAllScores(cachedScores);
      setFirstPage(cachedScores.slice(0, PAGE_SIZE));
      setModel(cachedModel);
    } else {
      setFirstPage(null);
      setAllScores(null);
    }

    // Fetch model list first
    apiJson<ModelSummary[]>("/v1/predictions/models")
      .then((models) => {
        if (models.length === 0) {
          setError("No trained models found.");
          setFirstPage([]);
          setAllScores([]);
          return;
        }
        const latest = models[0];
        setModel(latest);
        writeCache("mlpicks:model", latest);
        const base = `/v1/predictions/models/${latest.id}/scores`;

        // If no cache, fetch first page fast
        if (!cachedScores) {
          apiJson<Score[]>(`${base}?limit=${PAGE_SIZE}`)
            .then((rows) => setFirstPage(rows))
            .catch(() => setFirstPage([]));
        }

        // Always fetch full dataset in background
        apiJson<Score[]>(base)
          .then((s) => {
            setAllScores(s);
            writeCache("mlpicks:scores", s);
          })
          .catch(() => { if (!cachedScores) setAllScores([]); });
      })
      .catch((e) => {
        if (!cachedScores) {
          setFirstPage([]);
          setAllScores([]);
        }
        setError(e.message);
      });
  }, [user, flushKey]);

  const handleFlush = useCallback(() => {
    clearCache("mlpicks:");
    setFirstPage(null);
    setAllScores(null);
    setModel(null);
    setFlushKey((k) => k + 1);
  }, []);

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

  // Use full dataset when available, otherwise first page
  const hasAll = allScores !== null;
  const scores = allScores ?? firstPage ?? [];

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
  }, [allScores, firstPage]);

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
        case "kelly": va = a.kelly_fraction; vb = b.kelly_fraction; break;
        case "weight": va = a.suggested_weight; vb = b.suggested_weight; break;
        default: va = a.rank; vb = b.rank;
      }
      const cmp = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [allScores, firstPage, sortKey, sortDir]);

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

  const initialLoading = firstPage === null;

  if (loading || !user) return null;
  if (!initialLoading && error && scores.length === 0) {
    return (
      <div className="rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
        {error}
      </div>
    );
  }

  const withWeights = scores.filter((s) => s.suggested_weight > 0);
  const totalWeight = scores.reduce((s, x) => s + x.suggested_weight, 0);

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">
            ML Picks
            {!initialLoading && scores.length > 0 && (
              <span className="ml-2 text-base font-normal text-gray-500">
                {q && hasAll
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
        <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-8 text-center">
          <p className="text-gray-400">No scores available yet.</p>
          <p className="mt-2 text-sm text-gray-600">
            Run <code className="rounded bg-gray-800 px-1.5 py-0.5 text-xs">python -m app.cli score-universe</code> to score the universe.
          </p>
        </div>
      ) : (
        <>
          {/* Summary cards */}
          <div className="mb-6 grid gap-3 grid-cols-2 sm:grid-cols-4">
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
              label="Portfolio Util."
              value={fmtPct(totalWeight)}
              sub={`${withWeights.length} positions`}
            />
            <StatCard
              label="Countries"
              value={String(countryBreakdown.length)}
              sub={countryBreakdown.slice(0, 3).map(([c]) => c).join(", ")}
            />
          </div>

          {/* Country breakdown */}
          {countryBreakdown.length > 0 && (
            <div className="mb-6 rounded-xl border border-gray-800 bg-gray-900/80 p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
                Country Allocation
              </h2>
              <div className="flex flex-wrap gap-3">
                {countryBreakdown.map(([country, { count, weight }]) => (
                  <div key={country} className="flex items-center gap-2 text-sm">
                    <span className="font-mono text-white">{country}</span>
                    <span className="text-gray-500">{fmtPct(weight)}</span>
                    <span className="text-gray-600">({count})</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Search */}
          <div className="mb-4">
            <div className="relative w-full sm:w-64">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by ticker or company name..."
                className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 pr-8 text-sm text-gray-300 placeholder-gray-500"
              />
              {q && !hasAll && (
                <div className="absolute right-2.5 top-1/2 -translate-y-1/2">
                  <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-600 border-t-gray-400" />
                </div>
              )}
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
                    <th className="px-3 py-2">Confidence</th>
                    <th className="px-3 py-2 text-right cursor-pointer hover:text-gray-300" onClick={() => toggleSort("kelly")}>
                      Kelly{sortIcon("kelly")}
                    </th>
                    <th className="px-3 py-2 text-right cursor-pointer hover:text-gray-300" onClick={() => toggleSort("weight")}>
                      Weight{sortIcon("weight")}
                    </th>
                    <th className="px-3 py-2">Top Features</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((s) => (
                    <tr key={s.id} className="border-b border-gray-800/50 hover:bg-white/[0.015]">
                      <td className="px-3 py-2 font-mono text-gray-500">{s.rank}</td>
                      <td className="px-3 py-2">
                        <Link
                          to={`/companies/${s.ticker}`}
                          className="font-medium text-blue-400 hover:text-blue-300"
                        >
                          {s.ticker}
                        </Link>
                        <div className="text-xs text-gray-500">{s.company_name}</div>
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
                      <td className="px-3 py-2">
                        <span
                          className={`inline-block rounded-full border px-2 py-0.5 text-xs ${
                            TIER_COLORS[s.confidence_tier] ?? TIER_COLORS.negligible
                          }`}
                        >
                          {s.confidence_tier}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-gray-400">
                        {fmtPct(s.kelly_fraction)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-gray-400">
                        {s.suggested_weight > 0 ? fmtPct(s.suggested_weight) : "\u2014"}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(s.contributing_features)
                            .filter(([k]) => k !== "country" && k !== "sector")
                            .slice(0, 3)
                            .map(([feat, data]) => {
                              const d = data as { value: number; importance: number };
                              return (
                                <span
                                  key={feat}
                                  className="inline-block rounded bg-gray-800 px-1.5 py-0.5 text-xs text-gray-400"
                                  title={`${feat}: ${d.value} (importance: ${(d.importance * 100).toFixed(1)}%)`}
                                >
                                  {feat.replace(/_/g, " ")}
                                </span>
                              );
                            })}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {visible.length === 0 && q && (
                    <tr>
                      <td colSpan={9} className="px-3 py-8 text-center text-gray-500">
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
