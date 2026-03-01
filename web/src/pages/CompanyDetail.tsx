import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import ScoreCard from "@/components/ScoreCard";
import StockChart from "@/components/StockChart";

interface Risk {
  type: string;
  severity: string;
  description: string;
}

interface Evidence {
  series: string;
  value: number;
  date: string;
  artefact_id: string;
  source: string;
  source_url: string;
}

interface CompanyPacket {
  ticker: string;
  cik: string;
  company_name: string;
  gics_code: string;
  country_iso2: string;
  as_of: string;
  calc_version: string;
  summary_version: string;
  scores: {
    overall: number;
    fundamental: number;
    market: number;
  };
  rank: number;
  rank_total: number;
  component_data: {
    fundamental_ratios?: Record<string, number | null>;
    market_metrics?: Record<string, number | null>;
  };
  risks: Risk[];
  evidence: Evidence[] | null;
}

const RATIO_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  roe: { label: "Return on Equity", format: (v) => `${(v * 100).toFixed(1)}%` },
  net_margin: { label: "Net Margin", format: (v) => `${(v * 100).toFixed(1)}%` },
  debt_equity: { label: "Debt / Equity", format: (v) => `${v.toFixed(2)}x` },
  revenue_growth: { label: "Revenue Growth (YoY)", format: (v) => `${(v * 100).toFixed(1)}%` },
  eps_growth: { label: "EPS Growth (YoY)", format: (v) => `${(v * 100).toFixed(1)}%` },
  fcf_yield: { label: "FCF Yield", format: (v) => `${(v * 100).toFixed(1)}%` },
};

const MARKET_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  return_1y: { label: "1-Year Return", format: (v) => `${(v * 100).toFixed(1)}%` },
  max_drawdown: { label: "Max Drawdown (12mo)", format: (v) => `${(v * 100).toFixed(1)}%` },
  ma_spread: { label: "Price vs 200-Day MA", format: (v) => `${(v * 100).toFixed(1)}%` },
};

function severityColor(severity: string): string {
  if (severity === "high") return "border-red-700 bg-red-950/50 text-red-300";
  if (severity === "medium") return "border-yellow-700 bg-yellow-950/50 text-yellow-300";
  return "border-gray-700 bg-gray-800 text-gray-300";
}

function severityDot(severity: string): string {
  if (severity === "high") return "bg-red-400";
  if (severity === "medium") return "bg-yellow-400";
  return "bg-gray-400";
}

function rankColor(rank: number, total: number): string {
  const pct = rank / total;
  if (pct <= 0.3) return "text-green-400";
  if (pct <= 0.7) return "text-yellow-400";
  return "text-red-400";
}

function rankLabel(rank: number, total: number): string {
  if (rank === 1) return "Top ranked";
  if (rank <= Math.ceil(total * 0.3)) return "Upper tier";
  if (rank <= Math.ceil(total * 0.7)) return "Mid tier";
  return "Lower tier";
}

function formatEvidence(series: string, value: number): string {
  if (series === "equity_close") return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  return value.toFixed(2);
}

export default function CompanyDetail() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const { ticker: rawTicker } = useParams<{ ticker: string }>();
  const ticker = rawTicker?.toUpperCase() || "";
  const [packet, setPacket] = useState<CompanyPacket | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  useEffect(() => {
    if (user && ticker) {
      apiJson<CompanyPacket>(
        `/v1/company/${ticker}/summary?include_evidence=true`
      )
        .then(setPacket)
        .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
    }
  }, [user, ticker]);

  if (loading || !user) return null;

  if (error) {
    return (
      <div>
        <Link to="/companies" className="mb-4 inline-block text-sm text-brand hover:underline">
          &larr; Back to Companies
        </Link>
        <div className="rounded border border-red-800 bg-red-900/30 px-4 py-3 text-red-300">
          {error}
        </div>
      </div>
    );
  }

  if (!packet) {
    return <div className="text-gray-400">Loading...</div>;
  }

  const { scores, component_data, risks, evidence } = packet;
  const fundamentalRatios = component_data?.fundamental_ratios || {};
  const marketMetrics = component_data?.market_metrics || {};

  return (
    <div>
      <Link to="/companies" className="mb-6 inline-block text-sm text-gray-400 hover:text-white">
        &larr; All companies
      </Link>

      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold text-white">{packet.company_name}</h1>
          <span className="rounded bg-gray-800 px-2 py-1 text-sm text-gray-400">{packet.ticker}</span>
        </div>
        <div className="mt-2 flex items-center gap-4">
          <span className={`text-lg font-semibold ${rankColor(packet.rank, packet.rank_total)}`}>
            #{packet.rank} of {packet.rank_total}
          </span>
          <span className="text-sm text-gray-500">
            {rankLabel(packet.rank, packet.rank_total)}
          </span>
          <span className="text-sm text-gray-600">
            as of {packet.as_of}
          </span>
        </div>
      </div>

      {/* Stock chart */}
      <StockChart ticker={packet.ticker} />

      {/* Score cards */}
      <div className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-3">
        <ScoreCard label="Overall" score={scores.overall} />
        <ScoreCard label="Fundamental (60%)" score={scores.fundamental} />
        <ScoreCard label="Market (40%)" score={scores.market} />
      </div>

      {/* Risks */}
      {risks.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white">Risks</h2>
          <div className="space-y-2">
            {risks.map((r, i) => (
              <div key={i} className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${severityColor(r.severity)}`}>
                <span className={`mt-1.5 h-2 w-2 flex-shrink-0 rounded-full ${severityDot(r.severity)}`} />
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wide">
                    {r.severity}
                  </span>
                  <p className="mt-0.5 text-sm">{r.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Two-column layout for indicators */}
      <div className="mb-8 grid gap-6 md:grid-cols-2">
        {/* Fundamental ratios */}
        <div>
          <h2 className="mb-3 text-lg font-semibold text-white">Fundamental Ratios</h2>
          <div className="rounded-lg border border-gray-800 bg-gray-900">
            <div className="divide-y divide-gray-800/50">
              {Object.entries(fundamentalRatios).map(([key, val]) => {
                const meta = RATIO_LABELS[key];
                const isNeg = val != null && val < 0;
                return (
                  <div key={key} className="flex items-center justify-between px-4 py-2.5">
                    <span className="text-sm text-gray-400">
                      {meta?.label || key.replace(/_/g, " ")}
                    </span>
                    <span className={`font-mono text-sm font-medium ${isNeg ? "text-red-400" : "text-white"}`}>
                      {val != null && meta ? meta.format(val) : val != null ? String(val) : "\u2014"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Market metrics */}
        <div>
          <h2 className="mb-3 text-lg font-semibold text-white">Market Metrics</h2>
          <div className="rounded-lg border border-gray-800 bg-gray-900">
            <div className="divide-y divide-gray-800/50">
              {Object.entries(marketMetrics).map(([key, val]) => {
                const meta = MARKET_LABELS[key];
                const isNeg = val != null && val < 0;
                return (
                  <div key={key} className="flex items-center justify-between px-4 py-2.5">
                    <span className="text-sm text-gray-400">
                      {meta?.label || key.replace(/_/g, " ")}
                    </span>
                    <span className={`font-mono text-sm font-medium ${isNeg ? "text-red-400" : "text-white"}`}>
                      {val != null && meta ? meta.format(val) : val != null ? String(val) : "\u2014"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Evidence */}
      {evidence && evidence.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white">
            Evidence Chain
            <span className="ml-2 text-sm font-normal text-gray-500">
              {evidence.length} data points
            </span>
          </h2>
          <div className="overflow-x-auto rounded-lg border border-gray-800 bg-gray-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-3">Series</th>
                  <th className="px-4 py-3 text-right">Value</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3 text-xs font-normal normal-case text-gray-600">Artefact</th>
                </tr>
              </thead>
              <tbody>
                {evidence.map((e, i) => (
                  <tr key={i} className="border-b border-gray-800/50">
                    <td className="px-4 py-2 text-gray-300">
                      {e.series.replace(/_/g, " ")}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-white">
                      {formatEvidence(e.series, e.value)}
                    </td>
                    <td className="px-4 py-2 text-gray-400">{e.date}</td>
                    <td className="px-4 py-2 text-gray-500">{e.source}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-600">
                      {e.artefact_id.substring(0, 8)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Metadata */}
      <div className="mt-6 rounded-lg border border-gray-800/50 bg-gray-950 px-4 py-3 text-xs text-gray-600">
        calc_version: {packet.calc_version} &middot; summary_version: {packet.summary_version}
      </div>
    </div>
  );
}
