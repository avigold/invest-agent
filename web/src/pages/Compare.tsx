import { useState, useCallback, useRef, useEffect } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { exportToCsv, todayStr } from "@/lib/export";
import { queryKeys } from "@/lib/queries";
import CompareChart from "@/components/CompareChart";

// ── Types ────────────────────────────────────────────────────────────────

interface CompanyPacket {
  ticker: string;
  company_name: string;
  country_iso2: string;
  gics_code: string;
  scores: { overall: number; fundamental: number; market: number };
  rank: number;
  rank_total: number;
  component_data: {
    fundamental_ratios?: Record<string, number | null>;
    market_metrics?: Record<string, number | null>;
  };
}

interface MLScoreDetail {
  ticker: string;
  company_name: string;
  country: string;
  sector: string;
  probability: number;
  suggested_weight: number;
  fundamentals: {
    classification: string;
    composite_score: number;
  } | null;
  key_ratios?: Record<string, number | null>;
  market_cap_usd?: number | null;
}

interface SearchResult {
  ticker: string;
  name: string;
  cik: string | null;
  country_iso2: string;
  gics_code: string;
  market_cap: number | null;
  already_added: boolean;
}

// ── Format helpers ───────────────────────────────────────────────────────

function pct(v: number | null | undefined): string {
  return v != null ? `${(v * 100).toFixed(1)}%` : "\u2014";
}

function pctSigned(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const s = (v * 100).toFixed(1);
  return v > 0 ? `+${s}%` : `${s}%`;
}

function multiple(v: number | null | undefined): string {
  return v != null ? `${v.toFixed(1)}x` : "\u2014";
}

function fmtCap(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toLocaleString()}`;
}

function score1dp(v: number | null | undefined): string {
  return v != null ? v.toFixed(1) : "\u2014";
}

function rankStr(rank: number | null | undefined, total: number | null | undefined): string {
  if (rank == null || total == null) return "\u2014";
  return `#${rank} of ${total}`;
}

// ── Metric definitions ──────────────────────────────────────────────────

type ValueExtractor = (det: CompanyPacket | null, ml: MLScoreDetail | null) => number | string | null;

interface MetricDef {
  key: string;
  label: string;
  group: string;
  format: (v: number | string | null) => string;
  extract: ValueExtractor;
  numeric: boolean;
  higherIsBetter: boolean;
}

const METRIC_GROUPS = [
  "Overview",
  "Deterministic Scores",
  "ML Signals",
  "Valuation",
  "Profitability",
  "Growth",
  "Risk & Capital",
  "Performance",
] as const;

function ratioVal(
  ml: MLScoreDetail | null,
  det: CompanyPacket | null,
  key: string,
  detKey?: string,
): number | null {
  const mlVal = ml?.key_ratios?.[key];
  if (mlVal != null) return mlVal;
  const dKey = detKey ?? key;
  const detVal = det?.component_data?.fundamental_ratios?.[dKey];
  if (detVal != null) return detVal;
  return null;
}

function marketVal(
  ml: MLScoreDetail | null,
  det: CompanyPacket | null,
  key: string,
  detKey?: string,
): number | null {
  const mlVal = ml?.key_ratios?.[key];
  if (mlVal != null) return mlVal;
  const dKey = detKey ?? key;
  const detVal = det?.component_data?.market_metrics?.[dKey];
  if (detVal != null) return detVal;
  return null;
}

const METRICS: MetricDef[] = [
  // Overview
  {
    key: "country", label: "Country", group: "Overview",
    format: (v) => v != null ? String(v) : "\u2014",
    extract: (_d, ml) => ml?.country ?? null,
    numeric: false, higherIsBetter: true,
  },
  {
    key: "sector", label: "Sector", group: "Overview",
    format: (v) => v != null ? String(v) : "\u2014",
    extract: (_d, ml) => ml?.sector ?? null,
    numeric: false, higherIsBetter: true,
  },
  {
    key: "market_cap", label: "Market Cap", group: "Overview",
    format: (v) => fmtCap(v as number | null),
    extract: (_d, ml) => ml?.market_cap_usd ?? null,
    numeric: true, higherIsBetter: true,
  },
  // Deterministic Scores
  {
    key: "overall_score", label: "Overall Score", group: "Deterministic Scores",
    format: (v) => score1dp(v as number | null),
    extract: (d) => d?.scores?.overall ?? null,
    numeric: true, higherIsBetter: true,
  },
  {
    key: "fundamental_score", label: "Fundamental Score", group: "Deterministic Scores",
    format: (v) => score1dp(v as number | null),
    extract: (d) => d?.scores?.fundamental ?? null,
    numeric: true, higherIsBetter: true,
  },
  {
    key: "market_score", label: "Market Score", group: "Deterministic Scores",
    format: (v) => score1dp(v as number | null),
    extract: (d) => d?.scores?.market ?? null,
    numeric: true, higherIsBetter: true,
  },
  {
    key: "rank", label: "Rank", group: "Deterministic Scores",
    format: (v) => v != null ? String(v) : "\u2014",
    extract: (d) => d ? rankStr(d.rank, d.rank_total) : null,
    numeric: false, higherIsBetter: false,
  },
  // ML Signals
  {
    key: "probability", label: "Probability", group: "ML Signals",
    format: (v) => pct(v as number | null),
    extract: (_d, ml) => ml?.probability ?? null,
    numeric: true, higherIsBetter: true,
  },
  {
    key: "weight", label: "Weight", group: "ML Signals",
    format: (v) => pct(v as number | null),
    extract: (_d, ml) => ml?.suggested_weight ?? null,
    numeric: true, higherIsBetter: true,
  },
  {
    key: "classification", label: "Classification", group: "ML Signals",
    format: (v) => v != null ? String(v) : "\u2014",
    extract: (_d, ml) => ml?.fundamentals?.classification ?? null,
    numeric: false, higherIsBetter: true,
  },
  {
    key: "composite_score", label: "Composite Score", group: "ML Signals",
    format: (v) => score1dp(v as number | null),
    extract: (_d, ml) => ml?.fundamentals?.composite_score ?? null,
    numeric: true, higherIsBetter: true,
  },
  // Valuation
  {
    key: "pe_ratio", label: "P/E", group: "Valuation",
    format: (v) => multiple(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "pe_ratio"),
    numeric: true, higherIsBetter: false,
  },
  {
    key: "pb_ratio", label: "P/B", group: "Valuation",
    format: (v) => multiple(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "pb_ratio"),
    numeric: true, higherIsBetter: false,
  },
  // Profitability
  {
    key: "roe", label: "ROE", group: "Profitability",
    format: (v) => pct(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "roe"),
    numeric: true, higherIsBetter: true,
  },
  {
    key: "net_margin", label: "Net Margin", group: "Profitability",
    format: (v) => pct(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "net_margin"),
    numeric: true, higherIsBetter: true,
  },
  {
    key: "gross_margin", label: "Gross Margin", group: "Profitability",
    format: (v) => pct(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "gross_margin"),
    numeric: true, higherIsBetter: true,
  },
  {
    key: "operating_margin", label: "Operating Margin", group: "Profitability",
    format: (v) => pct(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "operating_margin"),
    numeric: true, higherIsBetter: true,
  },
  // Growth
  {
    key: "revenue_growth", label: "Revenue Growth", group: "Growth",
    format: (v) => pctSigned(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "revenue_growth"),
    numeric: true, higherIsBetter: true,
  },
  {
    key: "eps_growth", label: "EPS Growth", group: "Growth",
    format: (v) => pctSigned(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "eps_growth"),
    numeric: true, higherIsBetter: true,
  },
  // Risk & Capital
  {
    key: "debt_equity", label: "Debt / Equity", group: "Risk & Capital",
    format: (v) => multiple(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "debt_equity"),
    numeric: true, higherIsBetter: false,
  },
  {
    key: "current_ratio", label: "Current Ratio", group: "Risk & Capital",
    format: (v) => multiple(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "current_ratio"),
    numeric: true, higherIsBetter: true,
  },
  {
    key: "fcf_yield", label: "FCF Yield", group: "Risk & Capital",
    format: (v) => pct(v as number | null),
    extract: (d, ml) => ratioVal(ml, d, "fcf_yield"),
    numeric: true, higherIsBetter: true,
  },
  // Performance
  {
    key: "return_1y", label: "1-Year Return", group: "Performance",
    format: (v) => pctSigned(v as number | null),
    extract: (d, ml) => marketVal(ml, d, "momentum_12m", "return_1y"),
    numeric: true, higherIsBetter: true,
  },
  {
    key: "max_drawdown", label: "Max Drawdown", group: "Performance",
    format: (v) => pct(v as number | null),
    extract: (d, ml) => marketVal(ml, d, "max_dd_12m", "max_drawdown"),
    numeric: true, higherIsBetter: false,
  },
];

// ── Ticker data ─────────────────────────────────────────────────────────

interface TickerData {
  ticker: string;
  det: CompanyPacket | null;
  ml: MLScoreDetail | null;
  loading: boolean;
}

// ── Highlighting helpers ────────────────────────────────────────────────

function bestWorstIndices(
  values: (number | null)[],
  higherIsBetter: boolean,
): { best: number; worst: number } {
  let bestIdx = -1;
  let worstIdx = -1;
  let bestVal = higherIsBetter ? -Infinity : Infinity;
  let worstVal = higherIsBetter ? Infinity : -Infinity;

  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null) continue;
    if (higherIsBetter ? v > bestVal : v < bestVal) {
      bestVal = v;
      bestIdx = i;
    }
    if (higherIsBetter ? v < worstVal : v > worstVal) {
      worstVal = v;
      worstIdx = i;
    }
  }
  return { best: bestIdx, worst: worstIdx };
}

// ── Component ───────────────────────────────────────────────────────────

export default function Compare() {
  const { user, loading: authLoading } = useUser();
  const [searchParams, setSearchParams] = useSearchParams();

  // Tickers from URL
  const tickersParam = searchParams.get("tickers") || "";
  const tickers = tickersParam ? tickersParam.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean) : [];

  // Search state
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Click outside to close dropdown
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // URL sync helper
  const setTickers = useCallback(
    (newTickers: string[]) => {
      const params = new URLSearchParams();
      if (newTickers.length > 0) params.set("tickers", newTickers.join(","));
      setSearchParams(params, { replace: true });
    },
    [setSearchParams],
  );

  const addTicker = useCallback(
    (ticker: string) => {
      const t = ticker.toUpperCase();
      if (tickers.includes(t) || tickers.length >= 5) return;
      setTickers([...tickers, t]);
      setQuery("");
      setResults([]);
      setShowDropdown(false);
    },
    [tickers, setTickers],
  );

  const removeTicker = useCallback(
    (ticker: string) => {
      setTickers(tickers.filter((t) => t !== ticker));
    },
    [tickers, setTickers],
  );

  // Debounced search
  useEffect(() => {
    clearTimeout(debounceRef.current);
    if (query.length < 1) {
      setResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await apiJson<SearchResult[]>(`/v1/companies/search?q=${encodeURIComponent(query)}`);
        setResults(data.slice(0, 8));
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  // Handle Enter key — add typed ticker directly
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && query.trim()) {
        e.preventDefault();
        addTicker(query.trim());
      }
    },
    [query, addTicker],
  );

  // Parallel data fetching — deterministic + ML for each ticker
  const detQueries = useQueries({
    queries: tickers.map((ticker) => ({
      queryKey: queryKeys.company(ticker),
      queryFn: () => apiJson<CompanyPacket>(`/v1/company/${ticker}/summary?include_evidence=false`),
      retry: false as const,
      enabled: !!ticker,
    })),
  });

  const mlQueries = useQueries({
    queries: tickers.map((ticker) => ({
      queryKey: queryKeys.mlStock(ticker),
      queryFn: () => apiJson<MLScoreDetail>(`/v1/predictions/score/${ticker.replace(/\./g, "-")}`),
      retry: false as const,
      enabled: !!ticker,
    })),
  });

  // Combine data
  const tickerData: TickerData[] = tickers.map((ticker, i) => ({
    ticker,
    det: detQueries[i]?.data ?? null,
    ml: mlQueries[i]?.data ?? null,
    loading: detQueries[i]?.isLoading || mlQueries[i]?.isLoading,
  }));

  // CSV export
  const handleExport = useCallback(() => {
    if (tickers.length < 2) return;
    const headers = ["Metric", ...tickers];
    const rows: (string | number | null)[][] = [];
    for (const metric of METRICS) {
      const vals = tickerData.map((td) => {
        const raw = metric.extract(td.det, td.ml);
        return metric.format(raw as number | string | null);
      });
      rows.push([metric.label, ...vals]);
    }
    exportToCsv(`compare_${todayStr()}.csv`, headers, rows);
  }, [tickers, tickerData]);

  if (authLoading || !user) return null;

  // Group metrics for rendering
  const groupedMetrics = METRIC_GROUPS.map((group) => ({
    group,
    metrics: METRICS.filter((m) => m.group === group),
  }));

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Compare Companies</h1>
        <button
          onClick={handleExport}
          disabled={tickers.length < 2}
          title="Export CSV"
          className="rounded-lg border border-gray-700 bg-gray-800 p-2 text-gray-400 hover:bg-gray-700 hover:text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
        </button>
      </div>

      {/* Ticker selector */}
      <div className="mb-6 rounded-xl border border-gray-800 bg-gray-900/80 p-4">
        <div className="flex flex-wrap items-center gap-2">
          {/* Selected ticker chips */}
          {tickers.map((t) => (
            <span
              key={t}
              className="inline-flex items-center gap-1 rounded-full border border-gray-700 bg-gray-800 px-3 py-1 text-sm text-white"
            >
              <Link to={`/stocks/${t}`} className="hover:text-blue-400">
                {t}
              </Link>
              <button
                onClick={() => removeTicker(t)}
                className="ml-1 text-gray-500 hover:text-red-400"
                aria-label={`Remove ${t}`}
              >
                &times;
              </button>
            </span>
          ))}

          {/* Search input */}
          {tickers.length < 5 && (
            <div className="relative flex-1 min-w-[200px]">
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setShowDropdown(true);
                }}
                onFocus={() => {
                  if (results.length > 0 || query.length > 0) setShowDropdown(true);
                }}
                onKeyDown={handleKeyDown}
                placeholder={tickers.length === 0 ? "Search company name or ticker..." : "Add another..."}
                className="w-full rounded border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
              />
              {searching && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
                </div>
              )}

              {/* Search dropdown */}
              {showDropdown && results.length > 0 && (
                <div
                  ref={dropdownRef}
                  className="absolute left-0 top-full z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-gray-700 bg-gray-900 py-1 shadow-xl"
                >
                  {results
                    .filter((r) => !tickers.includes(r.ticker))
                    .map((r) => (
                      <button
                        key={r.ticker}
                        onClick={() => addTicker(r.ticker)}
                        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-gray-800"
                      >
                        <span>
                          <span className="font-medium text-white">{r.ticker}</span>
                          <span className="ml-2 text-gray-400">{r.name}</span>
                        </span>
                        <span className="text-xs text-gray-600">{r.country_iso2}</span>
                      </button>
                    ))}
                </div>
              )}
            </div>
          )}
        </div>
        {tickers.length >= 5 && (
          <p className="mt-2 text-xs text-gray-500">Maximum 5 companies. Remove one to add another.</p>
        )}
      </div>

      {/* Empty state */}
      {tickers.length < 2 && (
        <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-12 text-center">
          <p className="text-gray-400">
            {tickers.length === 0
              ? "Add at least 2 companies to compare."
              : "Add one more company to start comparing."}
          </p>
          <p className="mt-1 text-sm text-gray-600">
            Search by name or type a ticker and press Enter.
          </p>
        </div>
      )}

      {/* Chart overlay */}
      {tickers.length >= 2 && <CompareChart tickers={tickers} />}

      {/* Comparison table */}
      {tickers.length >= 2 && (
        <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
          <table className="w-full text-sm">
            {/* Header: ticker columns */}
            <thead>
              <tr className="border-b border-gray-800">
                <th className="sticky left-0 z-10 bg-gray-900 px-4 py-3 text-left text-xs uppercase text-gray-500">
                  Metric
                </th>
                {tickerData.map((td) => (
                  <th key={td.ticker} className="min-w-[140px] px-4 py-3 text-center">
                    <Link to={`/stocks/${td.ticker}`} className="font-semibold text-white hover:text-blue-400">
                      {td.ticker}
                    </Link>
                    {td.loading && (
                      <div className="mt-1 flex justify-center">
                        <div className="h-3 w-3 animate-spin rounded-full border border-gray-600 border-t-gray-300" />
                      </div>
                    )}
                    {!td.loading && (
                      <div className="mt-0.5 text-xs text-gray-500 truncate max-w-[140px]">
                        {td.ml?.company_name || td.det?.company_name || ""}
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groupedMetrics.map(({ group, metrics }) => {
                // Filter out rows where all values are null
                const visibleMetrics = metrics.filter((m) => {
                  return tickerData.some((td) => m.extract(td.det, td.ml) != null);
                });
                if (visibleMetrics.length === 0) return null;

                return (
                  <MetricGroup
                    key={group}
                    group={group}
                    metrics={visibleMetrics}
                    tickerData={tickerData}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── MetricGroup sub-component ───────────────────────────────────────────

function MetricGroup({
  group,
  metrics,
  tickerData,
}: {
  group: string;
  metrics: MetricDef[];
  tickerData: TickerData[];
}) {
  return (
    <>
      {/* Group header */}
      <tr className="border-t border-gray-800/50">
        <td
          colSpan={tickerData.length + 1}
          className="sticky left-0 z-10 bg-gray-900 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500"
        >
          {group}
        </td>
      </tr>
      {/* Metric rows */}
      {metrics.map((metric) => {
        const rawValues = tickerData.map((td) => metric.extract(td.det, td.ml));
        const numericValues = metric.numeric
          ? rawValues.map((v) => (typeof v === "number" ? v : null))
          : [];

        const nonNullCount = numericValues.filter((v) => v != null).length;
        const highlight =
          metric.numeric && nonNullCount >= 2
            ? bestWorstIndices(numericValues, metric.higherIsBetter)
            : { best: -1, worst: -1 };

        return (
          <tr key={metric.key} className="border-t border-gray-800/30">
            <td className="sticky left-0 z-10 bg-gray-900 px-4 py-2 text-sm text-gray-400 whitespace-nowrap">
              {metric.label}
            </td>
            {rawValues.map((val, i) => {
              const isBest = i === highlight.best;
              // Only mark worst when 3+ companies
              const isWorst = tickerData.length >= 3 && i === highlight.worst;
              let cellClass = "px-4 py-2 text-center font-mono text-sm ";
              if (isBest) cellClass += "bg-green-950/30 text-green-400";
              else if (isWorst) cellClass += "bg-red-950/30 text-red-400";
              else if (val == null) cellClass += "text-gray-600";
              else cellClass += "text-white";

              // Classification badge styling
              if (metric.key === "classification" && val != null) {
                const cls = String(val);
                const badgeClass =
                  cls === "Buy"
                    ? "border-green-700 bg-green-950/30 text-green-400"
                    : cls === "Hold"
                      ? "border-yellow-700 bg-yellow-950/30 text-yellow-400"
                      : "border-red-700 bg-red-950/30 text-red-400";
                return (
                  <td key={i} className="px-4 py-2 text-center">
                    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-semibold ${badgeClass}`}>
                      {cls}
                    </span>
                  </td>
                );
              }

              return (
                <td key={i} className={cellClass}>
                  {metric.format(val as number | string | null)}
                </td>
              );
            })}
          </tr>
        );
      })}
    </>
  );
}
