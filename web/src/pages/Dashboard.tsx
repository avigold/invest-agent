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

interface IndustryPreview {
  gics_code: string;
  industry_name: string;
  country_iso2: string;
  country_name: string;
  overall_score: number;
  rubric_score: number;
  rank: number;
}

export default function Dashboard() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const [recentJobs, setRecentJobs] = useState<JobRow[]>([]);
  const [topCountries, setTopCountries] = useState<CountryPreview[]>([]);
  const [topIndustries, setTopIndustries] = useState<IndustryPreview[]>([]);

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
      apiJson<IndustryPreview[]>("/v1/industries")
        .then((ind) => setTopIndustries(ind.slice(0, 5)))
        .catch(() => {});
    }
  }, [user]);

  if (loading || !user) return null;

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">
          Welcome, {user.name}
        </h1>
        <p className="text-gray-400">
          Plan: <span className="uppercase">{user.plan}</span>
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
