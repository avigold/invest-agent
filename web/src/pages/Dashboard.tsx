import { useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useUser } from "@/lib/auth";
import {
  useDashboardJobs,
  useDashboardCountries,
  useDashboardCompanies,
  useDashboardIndustries,
  useMLLatestScores,
  useMLModels,
  useMLModel,
  useSignalChanges,
  type SignalChangeItem,
} from "@/lib/queries";
import JobsTable, { JobRow } from "@/components/JobsTable";
import StockChart from "@/components/StockChart";

// ── Types ──────────────────────────────────────────────────────────────

interface CountryPreview {
  iso2: string;
  name: string;
  overall_score: number;
  rank: number;
}

interface CompanyPreview {
  ticker: string;
  name: string;
  gics_code: string;
  overall_score: number;
  fundamental_score: number;
  rank: number;
}

interface MLScore {
  id: string;
  ticker: string;
  company_name: string;
  country: string;
  sector: string;
  probability: number;
  confidence_tier: string;
  kelly_fraction: number;
  suggested_weight: number;
}

interface LatestScores {
  model_id: string;
  model_version: string;
  created_at: string;
  aggregate_metrics: { mean_auc?: number };
  scores: MLScore[];
}

interface ModelSummary {
  id: string;
  model_version: string;
  nickname: string | null;
  is_active: boolean;
  aggregate_metrics: {
    mean_auc?: number;
    std_auc?: number;
    n_folds?: number;
  };
  backtest_results: {
    total_return?: number;
    cagr?: number;
    sharpe?: number;
    max_drawdown?: number;
    hit_rate?: number;
    n_total_positions?: number;
    n_total_hits?: number;
  };
  created_at: string;
}

interface ModelDetail {
  id: string;
  backtest_results: {
    folds?: Array<{
      year: number;
      portfolio_return: number;
      n_positions: number;
      hit_rate: number;
    }>;
    total_return?: number;
  };
}

interface IndustryPreview {
  gics_code: string;
  industry_name: string;
  country_iso2: string;
  country_name: string;
  overall_score: number;
  rank: number;
}

// ── Helpers ────────────────────────────────────────────────────────────

function fmtPct(v: number | undefined | null, decimals = 1): string {
  return v != null ? `${(v * 100).toFixed(decimals)}%` : "\u2014";
}

const TIER_BAR_COLORS: Record<string, string> = {
  high: "bg-green-500",
  medium: "bg-yellow-500",
  low: "bg-gray-500",
  negligible: "bg-gray-700",
};

const TIER_BADGE_COLORS: Record<string, string> = {
  high: "border-green-800 bg-green-900/50 text-green-400",
  medium: "border-yellow-800 bg-yellow-900/50 text-yellow-300",
  low: "border-gray-700 bg-gray-800 text-gray-300",
  negligible: "border-gray-800 bg-gray-900 text-gray-500",
};

// ── Sub-components ─────────────────────────────────────────────────────

function HeroStat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "green" | "blue" | "red" | "default";
}) {
  const accentColor =
    accent === "green"
      ? "text-green-400"
      : accent === "blue"
        ? "text-blue-400"
        : accent === "red"
          ? "text-red-400"
          : "text-white";

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/80 px-5 py-4 text-center">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1.5">
        {label}
      </div>
      <div className={`text-2xl font-bold font-mono ${accentColor}`}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-600 mt-0.5">{sub}</div>}
    </div>
  );
}

function EquityCurve({
  folds,
}: {
  folds: Array<{ year: number; portfolio_return: number }>;
}) {
  if (folds.length === 0) return null;

  const maxAbs = Math.max(...folds.map((f) => Math.abs(f.portfolio_return)), 0.01);

  // Compute cumulative return
  let cumulative = 1;
  for (const f of folds) {
    cumulative *= 1 + f.portfolio_return;
  }
  const totalReturn = cumulative - 1;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-5 mb-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
          Walk-Forward Backtest
        </h2>
        <div className="text-right">
          <span className="text-xs text-gray-500">Cumulative: </span>
          <span className="font-mono font-bold text-green-400">
            {fmtPct(totalReturn, 0)}
          </span>
        </div>
      </div>
      <div className="flex items-end gap-2" style={{ height: "140px" }}>
        {folds.map((f) => {
          const pct = f.portfolio_return;
          const barHeight = Math.max((Math.abs(pct) / maxAbs) * 100, 4);
          const isPositive = pct >= 0;

          return (
            <div
              key={f.year}
              className="flex-1 flex flex-col items-center justify-end h-full"
            >
              {/* Label above bar */}
              <div
                className={`text-xs font-mono font-bold mb-1 ${
                  isPositive ? "text-green-400" : "text-red-400"
                }`}
              >
                {isPositive ? "+" : ""}
                {(pct * 100).toFixed(0)}%
              </div>
              {/* Bar */}
              <div
                className={`w-full rounded-t-md ${
                  isPositive ? "bg-green-500/60" : "bg-red-500/60"
                }`}
                style={{ height: `${barHeight}%`, minHeight: "4px" }}
              />
              {/* Year label */}
              <div className="text-[10px] text-gray-500 mt-1.5 font-mono">
                {f.year}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SpotlightCard({ pick }: { pick: MLScore }) {
  return (
    <div className="mb-8 rounded-xl border border-gray-800 bg-gray-900/80 overflow-hidden">
      <div className="p-5 pb-0">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono text-blue-400 bg-blue-900/40 border border-blue-800/50 rounded-full px-2 py-0.5">
                #1 Pick
              </span>
              <span
                className={`inline-block rounded-full border px-2 py-0.5 text-xs font-bold ${
                  TIER_BADGE_COLORS[pick.confidence_tier] ??
                  TIER_BADGE_COLORS.negligible
                }`}
              >
                {pick.confidence_tier}
              </span>
            </div>
            <Link
              to={`/stocks/${pick.ticker}`}
              className="block mt-2"
            >
              <span className="text-xl font-bold text-white hover:text-blue-400 transition-colors">
                {pick.company_name || pick.ticker}
              </span>
              <span className="ml-2 text-sm text-gray-500">{pick.ticker}</span>
            </Link>
            <div className="text-xs text-gray-500 mt-0.5">
              {pick.country} &middot; {pick.sector}
            </div>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold font-mono text-white">
              {fmtPct(pick.probability)}
            </div>
            <div className="text-xs text-gray-500">probability</div>
          </div>
        </div>

        {/* Probability bar */}
        <div className="h-2 w-full rounded-full bg-gray-800 mb-1">
          <div
            className="h-2 rounded-full bg-gradient-to-r from-blue-600 to-blue-400"
            style={{ width: `${Math.min(pick.probability * 100, 100)}%` }}
          />
        </div>
      </div>

      {/* Embedded stock chart */}
      <StockChart ticker={pick.ticker} embedded />
    </div>
  );
}

function ProbabilityBars({ picks }: { picks: MLScore[] }) {
  if (picks.length === 0) return null;

  const maxProb = Math.max(...picks.map((p) => p.probability), 0.01);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-5 mb-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
          Top ML Picks
        </h2>
        <Link to="/ml/picks" className="text-sm text-brand hover:underline">
          View all
        </Link>
      </div>
      <div className="space-y-2">
        {picks.map((s, i) => {
          const barWidth = (s.probability / maxProb) * 100;
          return (
            <div key={s.id} className="flex items-center gap-3">
              <div className="w-5 text-right text-xs font-mono text-gray-600">
                {i + 2}
              </div>
              <Link
                to={`/stocks/${s.ticker}`}
                className="w-28 flex-shrink-0 truncate text-sm text-white hover:text-blue-400"
                title={s.company_name}
              >
                {s.ticker}
              </Link>
              <div className="w-8 text-xs font-mono text-gray-500 flex-shrink-0">
                {s.country}
              </div>
              <div className="flex-1 min-w-0">
                <div className="h-5 w-full rounded bg-gray-800/60 overflow-hidden">
                  <div
                    className={`h-5 rounded ${
                      TIER_BAR_COLORS[s.confidence_tier] ?? TIER_BAR_COLORS.negligible
                    }`}
                    style={{ width: `${barWidth}%`, opacity: 0.7 }}
                  />
                </div>
              </div>
              <div className="w-14 text-right text-sm font-mono font-bold text-white flex-shrink-0">
                {fmtPct(s.probability)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SignalChangesCard({ changes }: { changes: SignalChangeItem[] }) {
  if (changes.length === 0) return null;

  const isUpgrade = (old_cls: string, new_cls: string) => {
    const rank: Record<string, number> = { Sell: 0, Hold: 1, Buy: 2 };
    return (rank[new_cls] ?? 0) > (rank[old_cls] ?? 0);
  };

  const timeAgo = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  };

  const clsBadge = (cls: string) => {
    if (cls === "Buy") return "text-green-400";
    if (cls === "Hold") return "text-yellow-400";
    return "text-red-400";
  };

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-5 mb-8">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400 mb-4">
        Signal Changes
      </h2>
      <div className="space-y-2">
        {changes.map((c) => {
          const up = isUpgrade(c.old_classification, c.new_classification);
          return (
            <div
              key={c.id}
              className="flex items-center gap-3 rounded-lg border border-gray-800/50 px-3 py-2"
            >
              {/* Direction arrow */}
              <span className={`text-lg ${up ? "text-green-400" : "text-red-400"}`}>
                {up ? "\u2191" : "\u2193"}
              </span>
              {/* Ticker */}
              <Link
                to={`/stocks/${c.ticker}`}
                className="w-20 flex-shrink-0 font-medium text-white hover:text-blue-400 text-sm"
              >
                {c.ticker}
              </Link>
              {/* Classification change */}
              <div className="flex items-center gap-1.5 text-sm">
                <span className={`font-semibold ${clsBadge(c.old_classification)}`}>
                  {c.old_classification}
                </span>
                <span className="text-gray-600">&rarr;</span>
                <span className={`font-semibold ${clsBadge(c.new_classification)}`}>
                  {c.new_classification}
                </span>
              </div>
              {/* System pill */}
              <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] uppercase text-gray-500">
                {c.system === "ml" ? "ML" : "Det"}
              </span>
              {/* Timestamp */}
              <span className="ml-auto text-xs text-gray-600">
                {timeAgo(c.detected_at)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main Dashboard ─────────────────────────────────────────────────────

export default function Dashboard() {
  const { user, loading } = useUser();
  const navigate = useNavigate();

  // Existing data
  const { data: allJobs = [] } = useDashboardJobs<JobRow[]>();
  const { data: allCountries = [] } = useDashboardCountries<CountryPreview[]>();
  const { data: topCompanies = [] } = useDashboardCompanies<CompanyPreview[]>();
  const { data: topIndustries = [] } = useDashboardIndustries<IndustryPreview[]>();
  const { data: latestScoresData } = useMLLatestScores<LatestScores>();

  // Signal changes
  const { data: signalChanges = [] } = useSignalChanges();

  // New: model stats for hero cards + equity curve
  const { data: allModels = [] } = useMLModels<ModelSummary[]>();
  const latestModel = allModels.find((m: ModelSummary) => m.is_active) ?? (allModels.length > 0 ? allModels[0] : null);
  const { data: modelDetail } = useMLModel<ModelDetail>(latestModel?.id ?? "");

  const recentJobs = allJobs.slice(0, 5);
  const topCountries = allCountries.slice(0, 3);
  const mlScores = latestScoresData?.scores ?? [];
  const spotlightPick = mlScores.length > 0 ? mlScores[0] : null;
  const barPicks = mlScores.slice(1, 10);
  const bt = latestModel?.backtest_results;
  const agg = latestModel?.aggregate_metrics;
  const folds = modelDetail?.backtest_results?.folds ?? [];

  useEffect(() => {
    if (!loading && !user) {
      navigate("/login", { replace: true });
    }
  }, [user, loading, navigate]);

  if (loading || !user) return null;

  return (
    <div>
      {/* Welcome */}
      <div
        className="mb-8 rounded-xl border border-gray-800 p-6"
        style={{
          background: "linear-gradient(135deg, #0a1525 0%, #040a18 100%)",
        }}
      >
        <p className="text-brand text-xs font-mono uppercase tracking-widest mb-2 select-none">
          Dashboard
        </p>
        <h1 className="text-2xl font-bold text-white">
          Welcome, {user.name}
        </h1>
        <p className="text-gray-500 text-sm mt-1">
          Plan:{" "}
          <span className="uppercase font-medium text-gray-400">
            {user.plan}
          </span>
        </p>
      </div>

      {/* ── Machine Learning section header ──────────────────────────── */}
      <div className="mb-5 mt-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
          Machine Learning
        </h2>
        <div className="mt-2 h-px bg-gray-800" />
      </div>

      {/* ── 1. Model Performance Hero Cards ──────────────────────────── */}
      {latestModel && bt && (
        <div className="mb-8 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <HeroStat
            label="Mean AUC"
            value={agg?.mean_auc?.toFixed(3) ?? "\u2014"}
            sub={agg?.std_auc != null ? `\u00B1${agg.std_auc.toFixed(3)}` : undefined}
            accent="blue"
          />
          <HeroStat
            label="Sharpe"
            value={bt.sharpe?.toFixed(2) ?? "\u2014"}
            accent="green"
          />
          <HeroStat
            label="CAGR"
            value={fmtPct(bt.cagr, 0)}
            accent="green"
          />
          <HeroStat
            label="Total Return"
            value={fmtPct(bt.total_return, 0)}
            accent="green"
          />
          <HeroStat
            label="Hit Rate"
            value={fmtPct(bt.hit_rate, 0)}
            sub={
              bt.n_total_hits != null
                ? `${bt.n_total_hits}/${bt.n_total_positions}`
                : undefined
            }
          />
        </div>
      )}

      {/* ── 2. Backtest Equity Curve ─────────────────────────────────── */}
      {folds.length > 0 && <EquityCurve folds={folds} />}

      {/* ── 3. Top Pick Spotlight ────────────────────────────────────── */}
      {spotlightPick && <SpotlightCard pick={spotlightPick} />}

      {/* ── 4. Probability Bars (#2-#10) ─────────────────────────────── */}
      {barPicks.length > 0 && <ProbabilityBars picks={barPicks} />}

      {/* ── 5. Signal Changes ──────────────────────────────────────── */}
      <SignalChangesCard changes={signalChanges} />

      {/* ── Traditional Fundamentals section header ─────────────────── */}
      <div className="mb-5 mt-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
          Traditional Fundamentals
        </h2>
        <div className="mt-2 h-px bg-gray-800" />
      </div>

      {/* Top Countries */}
      {topCountries.length > 0 && (
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Top Countries</h2>
            <Link
              to="/countries"
              className="text-sm text-brand hover:underline"
            >
              View all
            </Link>
          </div>
          <div className="grid grid-cols-3 gap-4">
            {topCountries.map((c) => (
              <Link
                key={c.iso2}
                to={`/countries/${c.iso2}`}
                className="rounded-lg border border-gray-800 bg-gray-900 p-4 hover:border-gray-700"
              >
                <div className="text-xs text-gray-500">#{c.rank}</div>
                <div className="text-lg font-bold text-white">{c.name}</div>
                <div className="text-2xl font-bold text-green-400">
                  {c.overall_score.toFixed(1)}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Top Companies */}
      {topCompanies.length > 0 && (
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">
              Top Companies
            </h2>
            <Link
              to="/companies"
              className="text-sm text-brand hover:underline"
            >
              View all
            </Link>
          </div>
          <div className="rounded-lg border border-gray-800 bg-gray-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-2 w-12">#</th>
                  <th className="px-4 py-2">Company</th>
                  <th className="px-4 py-2 text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {topCompanies.map((c) => (
                  <tr
                    key={c.ticker}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30"
                  >
                    <td className="px-4 py-2 text-gray-500">{c.rank}</td>
                    <td className="px-4 py-2">
                      <Link
                        to={`/stocks/${c.ticker}`}
                        className="text-white hover:text-brand"
                      >
                        {c.name}
                      </Link>
                      <span className="ml-2 text-xs text-gray-600">
                        {c.ticker}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono font-bold text-green-400">
                      {c.overall_score.toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Top Industries */}
      {topIndustries.length > 0 && (
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">
              Top Industries
            </h2>
            <Link
              to="/industries"
              className="text-sm text-brand hover:underline"
            >
              View all
            </Link>
          </div>
          <div className="rounded-lg border border-gray-800 bg-gray-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-2 w-12">#</th>
                  <th className="px-4 py-2">Sector</th>
                  <th className="px-4 py-2">Country</th>
                  <th className="px-4 py-2 text-right">Score</th>
                </tr>
              </thead>
              <tbody>
                {topIndustries.map((ind) => (
                  <tr
                    key={`${ind.gics_code}-${ind.country_iso2}`}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30"
                  >
                    <td className="px-4 py-2 text-gray-500">{ind.rank}</td>
                    <td className="px-4 py-2">
                      <Link
                        to={`/industries/${ind.gics_code}?iso2=${ind.country_iso2}`}
                        className="text-white hover:text-brand"
                      >
                        {ind.industry_name}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-gray-400">
                      {ind.country_name}
                    </td>
                    <td className="px-4 py-2 text-right font-mono font-bold text-green-400">
                      {ind.overall_score.toFixed(1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent Jobs */}
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Recent jobs</h2>
        <Link to="/jobs" className="text-sm text-brand hover:underline">
          View all
        </Link>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-900">
        <JobsTable jobs={recentJobs} />
      </div>
    </div>
  );
}
