import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";

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
  return_stats: {
    count: number;
    median: number;
    mean: number;
    min: number;
    max: number;
  };
  window_start_distribution: Record<string, number>;
  fundamental_stats: Record<string, FundamentalStat>;
}

interface ScreenResultFull {
  id: string;
  screen_name: string;
  screen_version: string;
  params: {
    return_threshold: number;
    window_years: number;
    lookback_years: number;
    include_fundamentals: boolean;
  };
  summary: {
    total_screened: number;
    matches_found: number;
    common_features: CommonFeatures;
  };
  matches: MatchRow[];
  created_at: string;
  job_id: string | null;
}

const METRIC_LABELS: Record<string, { label: string; fmt: (v: number) => string }> = {
  roe: { label: "ROE", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  net_margin: { label: "Net Margin", fmt: (v) => `${(v * 100).toFixed(1)}%` },
  debt_equity: { label: "Debt/Equity", fmt: (v) => `${v.toFixed(2)}x` },
  asset_turnover: { label: "Asset Turnover", fmt: (v) => `${v.toFixed(2)}x` },
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

function pct(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

function fmtMetric(key: string, v: number): string {
  return METRIC_LABELS[key]?.fmt(v) ?? v.toFixed(2);
}

export default function ScreenerResult() {
  const { id } = useParams<{ id: string }>();
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const [result, setResult] = useState<ScreenResultFull | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  useEffect(() => {
    if (user && id) {
      apiJson<ScreenResultFull>(`/v1/screener/results/${id}`)
        .then(setResult)
        .catch((e) => setError(e.message));
    }
  }, [user, id]);

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
    return (
      <div className="text-gray-500">Loading...</div>
    );
  }

  const cf = result.summary.common_features;

  return (
    <div>
      {/* Header */}
      <Link to="/screener" className="text-sm text-blue-400 hover:text-blue-300">
        &larr; Back to Screener
      </Link>

      <div className="mt-4 mb-6">
        <h1 className="text-2xl font-bold text-white">{result.screen_name}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {result.summary.matches_found} matches from {result.summary.total_screened} companies screened
          {" \u00B7 "}
          {result.params.window_years}yr windows over {result.params.lookback_years}yr lookback
        </p>
      </div>

      {/* Stat cards */}
      <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Matches" value={result.summary.matches_found} color="text-green-400" />
        <StatCard label="Screened" value={result.summary.total_screened} color="text-blue-400" />
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

      {/* Common Features */}
      {result.summary.matches_found > 0 && (
        <div className="mb-8 grid gap-6 lg:grid-cols-2">
          {/* Sector Distribution */}
          <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-5">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
              Sector Distribution
            </h3>
            {Object.entries(cf.sector_distribution).map(([sector, count]) => (
              <div key={sector} className="flex items-center justify-between py-1.5">
                <span className="text-sm text-gray-300">{sector}</span>
                <div className="flex items-center gap-3">
                  <div className="h-2 rounded-full bg-blue-900" style={{ width: `${Math.max(20, (count / result.summary.matches_found) * 120)}px` }}>
                    <div
                      className="h-full rounded-full bg-blue-500"
                      style={{ width: "100%" }}
                    />
                  </div>
                  <span className="w-8 text-right text-xs font-mono text-gray-400">{count}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Country Distribution */}
          <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-5">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-gray-400">
              Country Distribution
            </h3>
            {Object.entries(cf.country_distribution).map(([iso2, count]) => (
              <div key={iso2} className="flex items-center justify-between py-1.5">
                <span className="text-sm text-gray-300">{iso2}</span>
                <div className="flex items-center gap-3">
                  <div className="h-2 rounded-full bg-green-900" style={{ width: `${Math.max(20, (count / result.summary.matches_found) * 120)}px` }}>
                    <div className="h-full rounded-full bg-green-500" style={{ width: "100%" }} />
                  </div>
                  <span className="w-8 text-right text-xs font-mono text-gray-400">{count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Fundamental Profile */}
      {cf.fundamental_stats && Object.keys(cf.fundamental_stats).length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Fundamental Profile at Window Start
          </h2>
          <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-3">Metric</th>
                  <th className="px-4 py-3 text-right">Median</th>
                  <th className="px-4 py-3 text-right">Mean</th>
                  <th className="px-4 py-3 text-right">Min</th>
                  <th className="px-4 py-3 text-right">Max</th>
                  <th className="px-4 py-3 text-right">Count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(cf.fundamental_stats).map(([key, stats]) => (
                  <tr key={key} className="border-b border-gray-800/50">
                    <td className="px-4 py-3 text-gray-300">
                      {METRIC_LABELS[key]?.label ?? key}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-white">
                      {fmtMetric(key, stats.median)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-400">
                      {fmtMetric(key, stats.mean)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-500">
                      {fmtMetric(key, stats.min)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-500">
                      {fmtMetric(key, stats.max)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-500">
                      {stats.count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Matches Table */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Matches ({result.matches.length})
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
              {result.matches.map((m) => (
                <tr
                  key={m.ticker}
                  className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors"
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/companies/${m.ticker}`}
                      className="font-mono text-blue-400 hover:text-blue-300"
                    >
                      {m.ticker}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-300">{m.name}</td>
                  <td className="px-4 py-3 text-right">
                    <span className="font-mono font-bold text-green-400">
                      +{(m.return_pct * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {m.window_start} &rarr; {m.window_end}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">
                    ${m.start_price.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">
                    ${m.end_price.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{m.country_iso2}</td>
                </tr>
              ))}
              {result.matches.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-600">
                    No matches found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number | string;
  color: string;
}) {
  return (
    <div className="rounded-xl border border-gray-800 bg-[#0f172a] p-5">
      <div className={`text-3xl font-bold font-mono ${color}`}>{value}</div>
      <div className="mt-1 text-xs uppercase text-gray-500 tracking-wider">{label}</div>
    </div>
  );
}
