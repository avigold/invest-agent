import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { useScreenerResultDetail, queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MatchRow {
  ticker: string;
  name: string;
  country_iso2: string;
  gics_code: string;
  window_start: string;
  window_end: string;
  start_price: number;
  end_price: number;
  return_pct: number;
  fundamentals_at_start: Record<string, number | null>;
}

// v2 observation
interface ObservationRow {
  ticker: string;
  name: string;
  country_iso2: string;
  gics_code: string;
  obs_date: string;
  forward_return: number;
  forward_max_dd: number;
  label: string;
  momentum_12m: number | null;
  momentum_6m: number | null;
  volatility_12m: number | null;
  max_dd_12m: number | null;
  ma_spread: number | null;
  obs_price: number;
  fundamentals: Record<string, number | null>;
}

interface FeatureContrastRow {
  feature: string;
  winner_median: number;
  winner_p25: number;
  winner_p75: number;
  non_winner_median: number;
  non_winner_p25: number;
  non_winner_p75: number;
  winner_count: number;
  non_winner_count: number;
  lift: number;
  separation: number;
  direction: string;
}

interface ContrastData {
  features: FeatureContrastRow[];
  winner_count: number;
  non_winner_count: number;
  total_observations: number;
}

interface FundamentalStat {
  count: number;
  median: number;
  mean: number;
  min: number;
  max: number;
  stdev?: number;
}

interface CommonFeatures {
  sector_distribution: Record<string, number>;
  country_distribution: Record<string, number>;
  return_stats?: {
    count: number;
    median: number;
    mean: number;
    min: number;
    max: number;
  };
  window_start_distribution?: Record<string, number>;
  fundamental_stats?: Record<string, FundamentalStat>;
}

interface CandidateV1 {
  ticker: string;
  name: string;
  country_iso2: string;
  gics_code: string;
  match_score: number;
  matching_factors: string[];
  current_fundamentals: Record<string, number | null>;
  current_score: number;
}

interface CandidateV2Factor {
  feature: string;
  value: number | string;
  winner_median?: number;
  proximity: number;
  separation: number;
  direction: string;
}

interface CandidateV2 {
  ticker: string;
  name: string;
  country_iso2: string;
  gics_code: string;
  match_score: number;
  matching_factors: CandidateV2Factor[];
  current_fundamentals: Record<string, number | null>;
  current_market: Record<string, number | null>;
  current_score: number;
}

interface WinnerProfile {
  [metric: string]: { p25: number; median: number; p75: number; count: number };
}

interface ScreenAnalysis {
  model_id: string;
  analysis_version: string;
  sections: Record<string, string>;
  current_candidates: (CandidateV1 | CandidateV2)[];
  winner_profile?: WinnerProfile;
  contrast_summary?: {
    top_features: { feature: string; separation: number; lift: number; direction: string }[];
  };
  created_at: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface ScreenResultFull {
  id: string;
  screen_name: string;
  screen_version: string;
  params: Record<string, unknown>;
  summary: Record<string, unknown>;
  matches: (MatchRow | ObservationRow)[];
  analysis: ScreenAnalysis | null;
  created_at: string;
  job_id: string | null;
}

interface JobResponse {
  id: string;
  command: string;
  status: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const METRIC_LABELS: Record<string, { label: string; fmt: (v: number) => string }> = {
  roe: { label: "ROE", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  net_margin: { label: "Net Margin", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  debt_equity: { label: "Debt/Equity", fmt: (v) => `${v.toFixed(2)}x` },
  asset_turnover: { label: "Asset Turnover", fmt: (v) => `${v.toFixed(2)}x` },
  revenue_growth: { label: "Revenue Growth", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  fcf_yield: { label: "FCF Yield", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  momentum_12m: { label: "Momentum 12m", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  momentum_6m: { label: "Momentum 6m", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  volatility_12m: { label: "Volatility 12m", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  max_dd_12m: { label: "Max DD 12m", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  ma_spread: { label: "MA Spread", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  return_1y: { label: "1Y Return", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  max_drawdown: { label: "Max Drawdown", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  revenue: {
    label: "Revenue",
    fmt: (v) => {
      if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
      if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
      return `$${v.toFixed(0)}`;
    },
  },
  fcf: {
    label: "Free Cash Flow",
    fmt: (v) => {
      if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
      if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
      return `$${v.toFixed(0)}`;
    },
  },
};

const V1_SECTIONS: { key: string; label: string }[] = [
  { key: "pattern_summary", label: "Pattern Summary" },
  { key: "fundamental_profile", label: "Fundamental Profile" },
  { key: "sector_and_geography", label: "Sector & Geography" },
  { key: "timing_patterns", label: "Timing Patterns" },
  { key: "caveats", label: "Caveats" },
];

const V2_SECTIONS: { key: string; label: string }[] = [
  { key: "base_rate_context", label: "Base Rate Context" },
  { key: "distinctive_features", label: "Distinctive Features" },
  { key: "risk_factors", label: "Risk Factors" },
  { key: "sector_and_geography", label: "Sector & Geography" },
  { key: "fundamentals_vs_price", label: "Fundamentals vs Price Signals" },
  { key: "caveats", label: "Caveats" },
];

const FACTOR_COLORS: Record<string, string> = {
  roe: "bg-emerald-900/50 text-emerald-400 border-emerald-800",
  net_margin: "bg-blue-900/50 text-blue-400 border-blue-800",
  debt_equity: "bg-amber-900/50 text-amber-400 border-amber-800",
  revenue_growth: "bg-purple-900/50 text-purple-400 border-purple-800",
  fcf_yield: "bg-cyan-900/50 text-cyan-400 border-cyan-800",
  sector: "bg-pink-900/50 text-pink-400 border-pink-800",
  momentum_12m: "bg-orange-900/50 text-orange-400 border-orange-800",
  momentum_6m: "bg-orange-900/50 text-orange-300 border-orange-800",
  volatility_12m: "bg-red-900/50 text-red-400 border-red-800",
  max_dd_12m: "bg-red-900/50 text-red-300 border-red-800",
  ma_spread: "bg-teal-900/50 text-teal-400 border-teal-800",
};

function pct(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

function fmtMetric(key: string, v: number): string {
  return METRIC_LABELS[key]?.fmt(v) ?? v.toFixed(4);
}

function sepColor(sep: number): string {
  if (sep >= 0.5) return "text-green-400";
  if (sep >= 0.3) return "text-yellow-400";
  return "text-gray-400";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ScreenerResult() {
  const { id } = useParams<{ id: string }>();
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: result, error: queryError } = useScreenerResultDetail<ScreenResultFull>(id || "");
  const error = queryError ? (queryError instanceof Error ? queryError.message : "Failed to load") : "";
  const [jobStatus, setJobStatus] = useState<"idle" | "running" | "done" | "failed">("idle");
  const [jobError, setJobError] = useState("");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  const analyzePatterns = async () => {
    setJobStatus("running");
    setJobError("");
    try {
      const job = await apiJson<JobResponse>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "screen_analysis",
          params: { screen_result_id: id },
        }),
      });

      const pollInterval = setInterval(async () => {
        try {
          const status = await apiJson<JobResponse>(`/api/jobs/${job.id}`);
          if (status.status === "done") {
            clearInterval(pollInterval);
            setJobStatus("done");
            queryClient.invalidateQueries({ queryKey: queryKeys.screenerResult(id || "") });
          } else if (status.status === "failed" || status.status === "cancelled") {
            clearInterval(pollInterval);
            setJobStatus("failed");
            setJobError("Analysis failed. Check job logs for details.");
          }
        } catch {
          clearInterval(pollInterval);
          setJobStatus("failed");
          setJobError("Failed to check job status.");
        }
      }, 2000);
    } catch (e) {
      setJobStatus("failed");
      setJobError(e instanceof Error ? e.message : "Failed to start analysis job");
    }
  };

  if (loading || !user) return null;

  if (error) {
    return (
      <div>
        <Link to="/screener" className="text-sm text-blue-400 hover:text-blue-300">
          &larr; Back to Screener
        </Link>
        <div className="mt-4 rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      </div>
    );
  }

  if (!result) {
    return <div className="text-gray-500">Loading...</div>;
  }

  const isV2 = result.screen_version === "screen_v2";
  const analysis = result.analysis;

  if (isV2) {
    return <V2Layout result={result} analysis={analysis} jobStatus={jobStatus} jobError={jobError} analyzePatterns={analyzePatterns} />;
  }

  return <V1Layout result={result} analysis={analysis} jobStatus={jobStatus} jobError={jobError} analyzePatterns={analyzePatterns} />;
}

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------

function StatCard({ label, value, color, sub }: { label: string; value: number | string; color: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-[#0f172a] p-5">
      <div className={`text-3xl font-bold font-mono ${color}`}>{value}</div>
      <div className="mt-1 text-xs uppercase text-gray-500 tracking-wider">{label}</div>
      {sub && <div className="mt-0.5 text-[10px] text-gray-600">{sub}</div>}
    </div>
  );
}

function AnalyzeButton({ jobStatus, jobError, analyzePatterns }: {
  jobStatus: string;
  jobError: string;
  analyzePatterns: () => void;
}) {
  return (
    <div className="mb-8 rounded-xl border border-gray-800 bg-gray-900/80 p-6 text-center">
      {jobStatus === "running" ? (
        <div className="flex items-center justify-center gap-3 text-gray-400">
          <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Analyzing patterns and finding candidates...
        </div>
      ) : (
        <div>
          <p className="mb-3 text-gray-400">
            Use AI to identify deeper patterns and find current companies with similar profiles.
          </p>
          {jobError && <p className="mb-3 text-sm text-red-400">{jobError}</p>}
          <button
            onClick={analyzePatterns}
            className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-500 transition-colors"
          >
            Analyze Patterns
          </button>
        </div>
      )}
    </div>
  );
}

function DistributionPanels({ cf, total }: { cf: CommonFeatures; total: number }) {
  return (
    <div className="mb-8 grid gap-6 lg:grid-cols-2">
      <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-5">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">Sector Distribution</h3>
        {Object.entries(cf.sector_distribution || {}).map(([sector, count]) => (
          <div key={sector} className="flex items-center justify-between py-1.5">
            <span className="text-sm text-gray-300">{sector}</span>
            <div className="flex items-center gap-3">
              <div className="h-2 rounded-full bg-blue-900" style={{ width: `${Math.max(20, (count / Math.max(total, 1)) * 120)}px` }}>
                <div className="h-full rounded-full bg-blue-500" style={{ width: "100%" }} />
              </div>
              <span className="w-8 text-right text-xs font-mono text-gray-400">{count}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-5">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">Country Distribution</h3>
        {Object.entries(cf.country_distribution || {}).map(([iso2, count]) => (
          <div key={iso2} className="flex items-center justify-between py-1.5">
            <span className="text-sm text-gray-300">{iso2}</span>
            <div className="flex items-center gap-3">
              <div className="h-2 rounded-full bg-green-900" style={{ width: `${Math.max(20, (count / Math.max(total, 1)) * 120)}px` }}>
                <div className="h-full rounded-full bg-green-500" style={{ width: "100%" }} />
              </div>
              <span className="w-8 text-right text-xs font-mono text-gray-400">{count}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetadataFooter({ analysis }: { analysis: ScreenAnalysis }) {
  return (
    <div className="rounded-lg border border-gray-800/50 bg-gray-950 px-4 py-3 text-xs text-gray-600">
      {analysis.analysis_version} &middot; model: {analysis.model_id}
      {analysis.created_at && (
        <> &middot; generated {new Date(analysis.created_at).toLocaleDateString()}</>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// V2 Layout
// ---------------------------------------------------------------------------

interface LayoutProps {
  result: ScreenResultFull;
  analysis: ScreenAnalysis | null;
  jobStatus: string;
  jobError: string;
  analyzePatterns: () => void;
}

function V2Layout({ result, analysis, jobStatus, jobError, analyzePatterns }: LayoutProps) {
  const summary = result.summary;
  const totalObs = (summary.total_observations as number) || 0;
  const winnerCount = (summary.winner_count as number) || 0;
  const catastropheCount = (summary.catastrophe_count as number) || 0;
  const baseRate = (summary.base_rate as number) || 0;
  const contrast = summary.contrast as ContrastData | undefined;
  const catastropheProfile = summary.catastrophe_profile as ContrastData | undefined;
  const cf = (summary.common_features || {}) as CommonFeatures;
  const params = result.params;

  const observations = result.matches as ObservationRow[];
  const hasObservations = totalObs > 0;

  return (
    <div>
      <Link to="/screener" className="text-sm text-blue-400 hover:text-blue-300">&larr; Back to Screener</Link>

      <div className="mt-4 mb-6">
        <h1 className="text-2xl font-bold text-white">{result.screen_name}</h1>
        <p className="mt-1 text-sm text-gray-500">
          Fixed forward returns &middot; {(params.window_years as number) || 5}yr forward window
          &middot; {(summary.total_screened as number) || 0} companies
        </p>
      </div>

      {/* Stat cards */}
      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Observations" value={totalObs.toLocaleString()} color="text-blue-400" />
        <StatCard label="Winners" value={winnerCount} color="text-green-400" sub={`${(baseRate * 100).toFixed(1)}% base rate`} />
        <StatCard label="Catastrophes" value={catastropheCount} color="text-red-400" />
        <StatCard
          label="Screened"
          value={(summary.total_screened as number) || 0}
          color="text-gray-300"
        />
      </div>

      {/* Analyze button */}
      {hasObservations && !analysis && (
        <AnalyzeButton jobStatus={jobStatus} jobError={jobError} analyzePatterns={analyzePatterns} />
      )}

      {/* AI Analysis (v2 sections) */}
      {analysis && (
        <div className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-white">Pattern Analysis</h2>
          <div className="space-y-4">
            {V2_SECTIONS.map(({ key, label }) => {
              const text = analysis.sections[key];
              if (!text) return null;
              return (
                <div key={key} className="rounded-xl border border-gray-800 bg-gray-900/80 p-5">
                  <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-gray-400">{label}</h3>
                  <div className="text-sm leading-relaxed text-gray-300 whitespace-pre-line">{text}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Contrast Table */}
      {contrast && contrast.features.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Winner vs Non-Winner Contrast
          </h2>
          <p className="mb-4 text-xs text-gray-500">
            Features sorted by separation score — how well they divide winners from non-winners.
          </p>
          <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-3">Feature</th>
                  <th className="px-4 py-3 text-right">Winners (Med)</th>
                  <th className="px-4 py-3 text-right">Non-Winners (Med)</th>
                  <th className="px-4 py-3 text-right">Lift</th>
                  <th className="px-4 py-3">Separation</th>
                  <th className="px-4 py-3">Dir</th>
                </tr>
              </thead>
              <tbody>
                {contrast.features.map((f) => (
                  <tr key={f.feature} className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors">
                    <td className="px-4 py-3 text-gray-300 font-medium">
                      {METRIC_LABELS[f.feature]?.label ?? f.feature}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-white">
                      {fmtMetric(f.feature, f.winner_median)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-400">
                      {fmtMetric(f.feature, f.non_winner_median)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-300">
                      {isFinite(f.lift) ? `${f.lift.toFixed(2)}x` : "\u2014"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-20 rounded-full bg-gray-700">
                          <div
                            className={`h-2 rounded-full ${f.separation >= 0.5 ? "bg-green-500" : f.separation >= 0.3 ? "bg-yellow-500" : "bg-gray-500"}`}
                            style={{ width: `${f.separation * 100}%` }}
                          />
                        </div>
                        <span className={`font-mono text-xs ${sepColor(f.separation)}`}>
                          {f.separation.toFixed(3)}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {f.direction === "higher" ? "\u2191 higher" : "\u2193 lower"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Catastrophe Risk Table */}
      {catastropheProfile && catastropheProfile.features.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Catastrophe Risk Factors
          </h2>
          <p className="mb-4 text-xs text-gray-500">
            Features that predict forward drawdowns exceeding the catastrophe threshold.
          </p>
          <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-3">Feature</th>
                  <th className="px-4 py-3 text-right">Catastrophe (Med)</th>
                  <th className="px-4 py-3 text-right">Others (Med)</th>
                  <th className="px-4 py-3">Separation</th>
                  <th className="px-4 py-3">Dir</th>
                </tr>
              </thead>
              <tbody>
                {catastropheProfile.features.map((f) => (
                  <tr key={f.feature} className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors">
                    <td className="px-4 py-3 text-gray-300 font-medium">
                      {METRIC_LABELS[f.feature]?.label ?? f.feature}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-red-400">
                      {fmtMetric(f.feature, f.winner_median)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-400">
                      {fmtMetric(f.feature, f.non_winner_median)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-20 rounded-full bg-gray-700">
                          <div
                            className={`h-2 rounded-full ${f.separation >= 0.5 ? "bg-red-500" : f.separation >= 0.3 ? "bg-orange-500" : "bg-gray-500"}`}
                            style={{ width: `${f.separation * 100}%` }}
                          />
                        </div>
                        <span className="font-mono text-xs text-gray-400">{f.separation.toFixed(3)}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {f.direction === "higher" ? "\u2191 higher" : "\u2193 lower"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Current Candidates (v2) */}
      {analysis && analysis.current_candidates.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Current Candidates ({analysis.current_candidates.length})
          </h2>
          <p className="mb-4 text-xs text-gray-500">
            Companies today whose characteristics match the winner profile, weighted by feature discrimination.
          </p>
          <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3 text-right">Match</th>
                  <th className="px-4 py-3">Top Factors</th>
                  <th className="px-4 py-3 text-right">Score</th>
                  <th className="px-4 py-3">Country</th>
                </tr>
              </thead>
              <tbody>
                {analysis.current_candidates.map((c) => {
                  const factors = c.matching_factors as CandidateV2Factor[];
                  return (
                    <tr key={c.ticker} className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors">
                      <td className="px-4 py-3">
                        <Link to={`/companies/${c.ticker}`} className="font-mono text-blue-400 hover:text-blue-300">
                          {c.ticker}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-gray-300">{c.name}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="h-1.5 w-16 rounded-full bg-gray-700">
                            <div className="h-1.5 rounded-full bg-blue-500" style={{ width: `${c.match_score * 100}%` }} />
                          </div>
                          <span className="w-10 text-right font-mono text-xs text-gray-300">
                            {(c.match_score * 100).toFixed(0)}%
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {factors.slice(0, 4).map((f, i) => (
                            <span
                              key={i}
                              className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium ${
                                FACTOR_COLORS[f.feature] || "bg-gray-800 text-gray-400 border-gray-700"
                              }`}
                              title={typeof f.value === "number" ? `${f.feature}: ${fmtMetric(f.feature, f.value)} (prox: ${(f.proximity * 100).toFixed(0)}%)` : f.feature}
                            >
                              {METRIC_LABELS[f.feature]?.label ?? f.feature}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-gray-400">
                        {c.current_score.toFixed(1)}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500">{c.country_iso2}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Distributions */}
      {cf && <DistributionPanels cf={cf} total={winnerCount} />}

      {/* Winner observations table (collapsible) */}
      <WinnerObservationsTable observations={observations} />

      {/* Metadata footer */}
      {analysis && <MetadataFooter analysis={analysis} />}
    </div>
  );
}

function WinnerObservationsTable({ observations }: { observations: ObservationRow[] }) {
  const [expanded, setExpanded] = useState(false);
  const winners = observations.filter((o) => o.label === "winner");

  if (winners.length === 0) return null;

  return (
    <div className="mb-8">
      <button
        onClick={() => setExpanded(!expanded)}
        className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-gray-400 hover:text-gray-300"
      >
        <span className="text-xs">{expanded ? "\u25BC" : "\u25B6"}</span>
        Winner Observations ({winners.length})
      </button>
      {expanded && (
        <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="px-4 py-3">Ticker</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3 text-right">Forward Return</th>
                <th className="px-4 py-3 text-right">Forward DD</th>
                <th className="px-4 py-3 text-right">Mom 12m</th>
                <th className="px-4 py-3 text-right">Price</th>
                <th className="px-4 py-3">Country</th>
              </tr>
            </thead>
            <tbody>
              {winners.map((o, i) => (
                <tr key={`${o.ticker}-${o.obs_date}-${i}`} className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors">
                  <td className="px-4 py-3">
                    <Link to={`/companies/${o.ticker}`} className="font-mono text-blue-400 hover:text-blue-300">
                      {o.ticker}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-300">{o.name}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{o.obs_date}</td>
                  <td className="px-4 py-3 text-right font-mono font-bold text-green-400">
                    +{(o.forward_return * 100).toFixed(0)}%
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-red-400">
                    {(o.forward_max_dd * 100).toFixed(0)}%
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">
                    {o.momentum_12m != null ? `${(o.momentum_12m * 100).toFixed(0)}%` : "\u2014"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">
                    ${o.obs_price.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{o.country_iso2}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// V1 Layout (backward compat)
// ---------------------------------------------------------------------------

function V1Layout({ result, analysis, jobStatus, jobError, analyzePatterns }: LayoutProps) {
  const cf = (result.summary.common_features || {}) as CommonFeatures;
  const matchCount = (result.summary.matches_found as number) || 0;
  const matches = result.matches as MatchRow[];

  return (
    <div>
      <Link to="/screener" className="text-sm text-blue-400 hover:text-blue-300">&larr; Back to Screener</Link>

      <div className="mt-4 mb-6">
        <h1 className="text-2xl font-bold text-white">{result.screen_name}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {matchCount} matches from {(result.summary.total_screened as number) || 0} companies screened
          {" \u00B7 "}
          {(result.params.window_years as number) || 5}yr windows over {(result.params.lookback_years as number) || 20}yr lookback
        </p>
      </div>

      {/* Stat cards */}
      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Matches" value={matchCount} color="text-green-400" />
        <StatCard label="Screened" value={(result.summary.total_screened as number) || 0} color="text-blue-400" />
        <StatCard
          label="Median Return"
          value={cf.return_stats?.median ? pct(cf.return_stats.median) : "\u2014"}
          color="text-amber-400"
        />
        <StatCard
          label="Max Return"
          value={cf.return_stats?.max ? pct(cf.return_stats.max) : "\u2014"}
          color="text-purple-400"
        />
      </div>

      {/* Analyze button */}
      {matchCount > 0 && !analysis && (
        <AnalyzeButton jobStatus={jobStatus} jobError={jobError} analyzePatterns={analyzePatterns} />
      )}

      {/* AI Analysis (v1 sections) */}
      {analysis && (
        <div className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-white">Pattern Analysis</h2>
          <div className="space-y-4">
            {V1_SECTIONS.map(({ key, label }) => {
              const text = analysis.sections[key];
              if (!text) return null;
              return (
                <div key={key} className="rounded-xl border border-gray-800 bg-gray-900/80 p-5">
                  <h3 className="mb-2 text-sm font-semibold uppercase tracking-wider text-gray-400">{label}</h3>
                  <div className="text-sm leading-relaxed text-gray-300 whitespace-pre-line">{text}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* v1 Candidates */}
      {analysis && analysis.current_candidates.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Current Candidates ({analysis.current_candidates.length})
          </h2>
          <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3 text-right">Match</th>
                  <th className="px-4 py-3">Factors</th>
                  <th className="px-4 py-3 text-right">Score</th>
                  <th className="px-4 py-3">Country</th>
                </tr>
              </thead>
              <tbody>
                {analysis.current_candidates.map((c) => {
                  const factors = c.matching_factors as string[];
                  return (
                    <tr key={c.ticker} className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors">
                      <td className="px-4 py-3">
                        <Link to={`/companies/${c.ticker}`} className="font-mono text-blue-400 hover:text-blue-300">{c.ticker}</Link>
                      </td>
                      <td className="px-4 py-3 text-gray-300">{c.name}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="h-1.5 w-16 rounded-full bg-gray-700">
                            <div className="h-1.5 rounded-full bg-blue-500" style={{ width: `${c.match_score * 100}%` }} />
                          </div>
                          <span className="w-10 text-right font-mono text-xs text-gray-300">
                            {(c.match_score * 100).toFixed(0)}%
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {factors.map((f) => (
                            <span
                              key={f}
                              className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium ${
                                FACTOR_COLORS[f] || "bg-gray-800 text-gray-400 border-gray-700"
                              }`}
                            >
                              {METRIC_LABELS[f]?.label ?? f}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-gray-400">{c.current_score.toFixed(1)}</td>
                      <td className="px-4 py-3 text-xs text-gray-500">{c.country_iso2}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Distributions */}
      {matchCount > 0 && <DistributionPanels cf={cf} total={matchCount} />}

      {/* v1 Matches table */}
      <div className="mb-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Matches ({matches.length})
        </h2>
        <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="px-4 py-3">Ticker</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3 text-right">Return</th>
                <th className="px-4 py-3">Period</th>
                <th className="px-4 py-3 text-right">Start $</th>
                <th className="px-4 py-3 text-right">End $</th>
                <th className="px-4 py-3">Country</th>
              </tr>
            </thead>
            <tbody>
              {matches.map((m) => (
                <tr key={m.ticker} className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors">
                  <td className="px-4 py-3">
                    <Link to={`/companies/${m.ticker}`} className="font-mono text-blue-400 hover:text-blue-300">{m.ticker}</Link>
                  </td>
                  <td className="px-4 py-3 text-gray-300">{m.name}</td>
                  <td className="px-4 py-3 text-right">
                    <span className="font-mono font-bold text-green-400">+{(m.return_pct * 100).toFixed(0)}%</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{m.window_start} &rarr; {m.window_end}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">${m.start_price.toFixed(2)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">${m.end_price.toFixed(2)}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{m.country_iso2}</td>
                </tr>
              ))}
              {matches.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-600">No matches found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Metadata footer */}
      {analysis && <MetadataFooter analysis={analysis} />}
    </div>
  );
}
