import { useNavigate, useParams, useSearchParams, Link } from "react-router-dom";
import { useEffect } from "react";
import { useUser } from "@/lib/auth";
import { useIndustryDetail } from "@/lib/queries";
import ScoreCard from "@/components/ScoreCard";

interface Signal {
  indicator: string;
  value: number | null;
  favorable_when: string;
  score: number;
  floor: number | null;
  ceiling: number | null;
  reason?: string;
}

interface Risk {
  type: string;
  severity: string;
  description: string;
}

interface IndustrySummary {
  gics_code: string;
  industry_name: string;
  country_iso2: string;
  country_name: string;
  as_of: string;
  calc_version: string;
  summary_version: string;
  scores: {
    overall: number;
  };
  rank: number;
  rank_total: number;
  component_data: {
    raw_score: number;
    signals: Signal[];
    country_macro_summary?: Record<string, number>;
  };
  risks: Risk[];
}

function scoreColor(score: number): string {
  if (score >= 60) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function severityColor(severity: string): string {
  if (severity === "high") return "text-red-400 bg-red-950/50";
  if (severity === "medium") return "text-yellow-400 bg-yellow-950/50";
  return "text-gray-400 bg-gray-800";
}

function formatIndicator(name: string): string {
  return name
    .replace(/_pct$/, "")
    .replace(/_bps$/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(indicator: string, value: number | null): string {
  if (value === null) return "N/A";
  if (indicator.endsWith("_bps")) return `${value.toFixed(0)} bps`;
  if (indicator === "stability_index") return value.toFixed(3);
  return `${value.toFixed(1)}%`;
}

export default function IndustryDetail() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const { gics_code } = useParams<{ gics_code: string }>();
  const [searchParams] = useSearchParams();
  const iso2 = searchParams.get("iso2") || "US";
  const { data: summary, error, isLoading } = useIndustryDetail<IndustrySummary>(gics_code || "", iso2);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  if (loading || !user) return null;

  if (error) {
    return (
      <div className="rounded border border-red-800 bg-red-900/30 px-4 py-3 text-red-300">
        {(error as Error).message}
      </div>
    );
  }

  if (isLoading || !summary) {
    return <p className="text-gray-500">Loading...</p>;
  }

  const { scores, component_data, risks } = summary;
  const tierPct = summary.rank / summary.rank_total;
  const tierLabel =
    tierPct <= 0.3 ? "Top Tier" : tierPct <= 0.7 ? "Mid Tier" : "Bottom Tier";
  const tierColor =
    tierPct <= 0.3
      ? "text-green-400"
      : tierPct <= 0.7
        ? "text-yellow-400"
        : "text-red-400";

  return (
    <div>
      {/* Back link */}
      <Link
        to="/industries"
        className="mb-4 inline-block text-sm text-gray-400 hover:text-white"
      >
        &larr; All Industries
      </Link>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">
            {summary.industry_name}
            <span className="ml-3 text-base text-gray-500">
              GICS {summary.gics_code}
            </span>
          </h1>
          <p className="mt-1 text-gray-400">
            <Link
              to={`/countries/${summary.country_iso2}`}
              className="hover:text-white transition-colors"
            >
              {summary.country_name}
            </Link>
            <span className="mx-2 text-gray-600">|</span>
            <span className={tierColor}>
              #{summary.rank}/{summary.rank_total} {tierLabel}
            </span>
            <span className="mx-2 text-gray-600">|</span>
            <span className="text-sm text-gray-500">
              as of {summary.as_of}
            </span>
          </p>
        </div>
      </div>

      {/* Score card */}
      <div className="mb-6">
        <ScoreCard label="Overall Score" score={scores.overall} />
      </div>

      {/* Risks */}
      {risks.length > 0 && (
        <div className="mb-6 rounded-lg border border-gray-800 bg-gray-900 p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase text-gray-500">
            Risk Flags
          </h2>
          <div className="space-y-2">
            {risks.map((r, i) => (
              <div key={i} className="flex items-center gap-3">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium ${severityColor(r.severity)}`}
                >
                  {r.severity}
                </span>
                <span className="text-sm text-gray-300">{r.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Macro Sensitivity Signals */}
      <div className="mb-6 rounded-lg border border-gray-800 bg-gray-900 p-4">
        <h2 className="mb-3 text-sm font-semibold uppercase text-gray-500">
          Macro Sensitivity Signals
        </h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
              <th className="px-4 py-2">Indicator</th>
              <th className="px-4 py-2 text-right">Value</th>
              <th className="px-4 py-2 text-center">Favorable When</th>
              <th className="px-4 py-2 text-right">Score</th>
            </tr>
          </thead>
          <tbody>
            {component_data.signals.map((s) => (
              <tr
                key={s.indicator}
                className="border-b border-gray-800/50"
              >
                <td className="px-4 py-2 text-gray-300">
                  {formatIndicator(s.indicator)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-gray-300">
                  {formatValue(s.indicator, s.value)}
                </td>
                <td className="px-4 py-2 text-center text-gray-500">
                  {s.favorable_when}
                </td>
                <td className={`px-4 py-2 text-right font-mono font-bold ${scoreColor(s.score)}`}>
                  {s.score.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Country Macro Summary */}
      {component_data.country_macro_summary &&
        Object.keys(component_data.country_macro_summary).length > 0 && (
          <div className="mb-6 rounded-lg border border-gray-800 bg-gray-900 p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase text-gray-500">
              Country Macro Context
            </h2>
            <div className="grid grid-cols-2 gap-x-8 gap-y-2 sm:grid-cols-3">
              {Object.entries(component_data.country_macro_summary).map(
                ([key, val]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-sm text-gray-500">
                      {key.replace(/_/g, " ")}
                    </span>
                    <span className="font-mono text-sm text-gray-300">
                      {typeof val === "number" ? val.toFixed(2) : String(val)}
                    </span>
                  </div>
                )
              )}
            </div>
          </div>
        )}

      {/* Metadata */}
      <div className="text-xs text-gray-600">
        calc_version: {summary.calc_version} | summary_version:{" "}
        {summary.summary_version}
      </div>
    </div>
  );
}
