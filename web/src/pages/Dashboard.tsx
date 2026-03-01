import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
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

interface BuyRecommendation {
  ticker: string;
  name: string;
  country_iso2: string;
  composite_score: number;
  classification: string;
  rank: number;
}

interface IndustryPreview {
  gics_code: string;
  industry_name: string;
  country_iso2: string;
  country_name: string;
  overall_score: number;
  rank: number;
}

export default function Dashboard() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const [recentJobs, setRecentJobs] = useState<JobRow[]>([]);
  const [topCountries, setTopCountries] = useState<CountryPreview[]>([]);
  const [topCompanies, setTopCompanies] = useState<CompanyPreview[]>([]);
  const [topIndustries, setTopIndustries] = useState<IndustryPreview[]>([]);
  const [topBuys, setTopBuys] = useState<BuyRecommendation[]>([]);

  useEffect(() => {
    if (!loading && !user) {
      navigate("/login", { replace: true });
    }
  }, [user, loading, navigate]);

  useEffect(() => {
    if (user) {
      apiJson<JobRow[]>("/api/jobs")
        .then((jobs) => setRecentJobs(jobs.slice(0, 5)))
        .catch(() => {});
      apiJson<CountryPreview[]>("/v1/countries")
        .then((c) => setTopCountries(c.slice(0, 3)))
        .catch(() => {});
      apiJson<CompanyPreview[]>("/v1/companies")
        .then((c) => setTopCompanies(c.slice(0, 5)))
        .catch(() => {});
      apiJson<IndustryPreview[]>("/v1/industries")
        .then((ind) => setTopIndustries(ind.slice(0, 5)))
        .catch(() => {});
      apiJson<BuyRecommendation[]>("/v1/recommendations?classification=Buy")
        .then((recs) => setTopBuys(recs.slice(0, 5)))
        .catch(() => {});
    }
  }, [user]);

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

      {topBuys.length > 0 && (
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Top Buy Recommendations</h2>
            <Link to="/recommendations" className="text-sm text-brand hover:underline">
              View all
            </Link>
          </div>
          <div className="rounded-lg border border-gray-800 bg-gray-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-2 w-12">#</th>
                  <th className="px-4 py-2">Company</th>
                  <th className="px-4 py-2">Country</th>
                  <th className="px-4 py-2 text-right">Composite</th>
                  <th className="px-4 py-2 text-center">Signal</th>
                </tr>
              </thead>
              <tbody>
                {topBuys.map((r) => (
                  <tr
                    key={r.ticker}
                    className="border-b border-gray-800/50 hover:bg-gray-800/30"
                  >
                    <td className="px-4 py-2 text-gray-500">{r.rank}</td>
                    <td className="px-4 py-2">
                      <Link
                        to={`/recommendations/${r.ticker}`}
                        className="text-white hover:text-brand"
                      >
                        {r.name}
                      </Link>
                      <span className="ml-2 text-xs text-gray-600">{r.ticker}</span>
                    </td>
                    <td className="px-4 py-2 text-gray-400">{r.country_iso2}</td>
                    <td className="px-4 py-2 text-right font-mono font-bold text-green-400">
                      {r.composite_score.toFixed(1)}
                    </td>
                    <td className="px-4 py-2 text-center">
                      <span className="inline-block rounded-full border border-green-800 bg-green-900/50 px-3 py-0.5 text-xs font-bold text-green-400">
                        Buy
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
                        to={`/companies/${c.ticker}`}
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
