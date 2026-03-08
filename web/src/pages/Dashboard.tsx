import { useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useUser } from "@/lib/auth";
import {
  useDashboardJobs,
  useDashboardCountries,
  useDashboardCompanies,
  useDashboardIndustries,
  useMLLatestScores,
} from "@/lib/queries";
import JobsTable, { JobRow } from "@/components/JobsTable";

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

interface IndustryPreview {
  gics_code: string;
  industry_name: string;
  country_iso2: string;
  country_name: string;
  overall_score: number;
  rank: number;
}

function fmtPct(v: number | undefined | null, decimals = 1): string {
  return v != null ? `${(v * 100).toFixed(decimals)}%` : "\u2014";
}

const TIER_COLORS: Record<string, string> = {
  high: "border-green-800 bg-green-900/50 text-green-400",
  medium: "border-yellow-800 bg-yellow-900/50 text-yellow-300",
  low: "border-gray-700 bg-gray-800 text-gray-300",
  negligible: "border-gray-800 bg-gray-900 text-gray-500",
};

export default function Dashboard() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const { data: allJobs = [] } = useDashboardJobs<JobRow[]>();
  const { data: allCountries = [] } = useDashboardCountries<CountryPreview[]>();
  const { data: topCompanies = [] } = useDashboardCompanies<CompanyPreview[]>();
  const { data: topIndustries = [] } = useDashboardIndustries<IndustryPreview[]>();
  const { data: latestScoresData } = useMLLatestScores<LatestScores>();

  const recentJobs = allJobs.slice(0, 5);
  const topCountries = allCountries.slice(0, 3);
  const mlScores = latestScoresData?.scores ?? [];
  const mlModel = latestScoresData
    ? { version: latestScoresData.model_version, auc: latestScoresData.aggregate_metrics?.mean_auc }
    : null;

  useEffect(() => {
    if (!loading && !user) {
      navigate("/login", { replace: true });
    }
  }, [user, loading, navigate]);

  if (loading || !user) return null;

  return (
    <div>
      <div className="mb-8 rounded-xl border border-gray-800 p-6" style={{ background: "linear-gradient(135deg, #0a1525 0%, #040a18 100%)" }}>
        <p className="text-brand text-xs font-mono uppercase tracking-widest mb-2 select-none">
          Dashboard
        </p>
        <h1 className="text-2xl font-bold text-white">
          Welcome, {user.name}
        </h1>
        <p className="text-gray-500 text-sm mt-1">
          Plan: <span className="uppercase font-medium text-gray-400">{user.plan}</span>
        </p>
      </div>

      {topCountries.length > 0 && (
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Top Countries</h2>
            <Link to="/countries" className="text-sm text-brand hover:underline">
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

      {/* ML Picks — Hero section */}
      <div className="mb-8">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-white">Top ML Picks</h2>
            {mlModel && (
              <p className="text-xs text-gray-500">
                Model: {mlModel.version}
                {mlModel.auc != null && <> &middot; AUC {mlModel.auc.toFixed(3)}</>}
              </p>
            )}
          </div>
          <Link to="/ml/picks" className="text-sm text-brand hover:underline">
            View all
          </Link>
        </div>
        {mlScores.length > 0 ? (
          <div className="rounded-lg border border-gray-800 bg-gray-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-2 w-12">#</th>
                  <th className="px-4 py-2">Company</th>
                  <th className="px-4 py-2">Country</th>
                  <th className="px-4 py-2 text-right">Probability</th>
                  <th className="px-4 py-2 text-center">Confidence</th>
                  <th className="px-4 py-2 text-right">Kelly</th>
                  <th className="px-4 py-2 text-right">Weight</th>
                </tr>
              </thead>
              <tbody>
                {mlScores.map((s, i) => (
                  <tr
                    key={s.id}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30"
                  >
                    <td className="px-4 py-2 text-gray-500">{i + 1}</td>
                    <td className="px-4 py-2">
                      <Link
                        to={`/stocks/${s.ticker}`}
                        className="text-white hover:text-brand"
                      >
                        {s.company_name || s.ticker}
                      </Link>
                      <span className="ml-2 text-xs text-gray-600">{s.ticker}</span>
                    </td>
                    <td className="px-4 py-2 font-mono text-gray-400">{s.country || "\u2014"}</td>
                    <td className="px-4 py-2 text-right font-mono font-bold text-white">
                      {fmtPct(s.probability)}
                    </td>
                    <td className="px-4 py-2 text-center">
                      <span
                        className={`inline-block rounded-full border px-2 py-0.5 text-xs font-bold ${
                          TIER_COLORS[s.confidence_tier] ?? TIER_COLORS.negligible
                        }`}
                      >
                        {s.confidence_tier}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-gray-400">
                      {fmtPct(s.kelly_fraction)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-gray-400">
                      {s.suggested_weight > 0 ? fmtPct(s.suggested_weight) : "\u2014"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-6 text-center">
            <p className="text-gray-400">No ML scores available yet.</p>
            <p className="mt-2 text-xs text-gray-600">
              Run{" "}
              <code className="rounded bg-gray-800 px-1.5 py-0.5 text-xs">
                python -m app.cli score-universe
              </code>{" "}
              to score the universe.
            </p>
          </div>
        )}
      </div>

      {topCompanies.length > 0 && (
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Top Companies</h2>
            <Link to="/companies" className="text-sm text-brand hover:underline">
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
                      <span className="ml-2 text-xs text-gray-600">{c.ticker}</span>
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

      {topIndustries.length > 0 && (
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Top Industries</h2>
            <Link to="/industries" className="text-sm text-brand hover:underline">
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
                    <td className="px-4 py-2 text-gray-400">{ind.country_name}</td>
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

      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Recent jobs</h2>
        <Link
          to="/jobs"
          className="text-sm text-brand hover:underline"
        >
          View all
        </Link>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-900">
        <JobsTable jobs={recentJobs} />
      </div>
    </div>
  );
}
