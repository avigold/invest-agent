import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";

interface ScreenResultSummary {
  id: string;
  screen_name: string;
  screen_version?: string;
  params: {
    return_threshold?: number;
    window_years?: number;
    lookback_years?: number;
  };
  summary: {
    total_screened: number | null;
    matches_found: number | null;
    total_observations?: number | null;
    winner_count?: number | null;
    base_rate?: number | null;
  };
  created_at: string;
  job_id: string | null;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Screener() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const [results, setResults] = useState<ScreenResultSummary[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Form state
  const [returnThreshold, setReturnThreshold] = useState(300);
  const [windowYears, setWindowYears] = useState(5);
  const [lookbackYears, setLookbackYears] = useState(20);
  const [includeFundamentals, setIncludeFundamentals] = useState(true);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  useEffect(() => {
    if (user) {
      apiJson<ScreenResultSummary[]>("/v1/screener/results")
        .then(setResults)
        .catch(() => {});
    }
  }, [user]);

  const runScreen = async () => {
    setSubmitting(true);
    setError("");
    try {
      const job = await apiJson<{ id: string }>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "stock_screen",
          params: {
            screen_version: "v2",
            return_threshold: returnThreshold / 100,
            window_years: windowYears,
            lookback_years: lookbackYears,
            include_fundamentals: includeFundamentals,
          },
        }),
      });
      navigate(`/jobs/${job.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to submit screen");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading || !user) return null;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Historical Stock Screener</h1>
        <p className="mt-1 text-sm text-gray-500">
          Find companies that hit exceptional return thresholds and analyze their common features
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Configuration */}
      <div className="mb-8 rounded-xl border border-gray-800 bg-gray-900/80 p-6">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Configure Screen
        </h2>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Return Threshold</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={50}
                max={10000}
                step={50}
                value={returnThreshold}
                onChange={(e) => setReturnThreshold(Number(e.target.value))}
                className="w-24 rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
              />
              <span className="text-sm text-gray-400">% gain</span>
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Window Size</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={20}
                value={windowYears}
                onChange={(e) => setWindowYears(Number(e.target.value))}
                className="w-24 rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
              />
              <span className="text-sm text-gray-400">years</span>
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Lookback Period</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={5}
                max={30}
                value={lookbackYears}
                onChange={(e) => setLookbackYears(Number(e.target.value))}
                className="w-24 rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
              />
              <span className="text-sm text-gray-400">years</span>
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Options</label>
            <label className="flex items-center gap-2 mt-2">
              <input
                type="checkbox"
                checked={includeFundamentals}
                onChange={(e) => setIncludeFundamentals(e.target.checked)}
                className="rounded border-gray-700 bg-gray-800 text-blue-500"
              />
              <span className="text-sm text-gray-300">Include fundamentals</span>
            </label>
          </div>
        </div>

        <div className="mt-6">
          <button
            onClick={runScreen}
            disabled={submitting}
            className="rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {submitting ? "Submitting..." : "Run Screen"}
          </button>
          <p className="mt-2 text-xs text-gray-600">
            Screens {"\u007E"}136 companies from the database. Takes 2-5 minutes.
          </p>
        </div>
      </div>

      {/* Past Results */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Past Results ({results.length})
        </h2>
        <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="px-4 py-3">Screen</th>
                <th className="px-4 py-3 text-right">Winners</th>
                <th className="px-4 py-3 text-right">Observations</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr
                  key={r.id}
                  className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors"
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/screener/${r.id}`}
                      className="font-medium text-blue-400 hover:text-blue-300"
                    >
                      {r.screen_name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-white">
                    {r.screen_version === "screen_v2"
                      ? (r.summary.winner_count ?? "\u2014")
                      : (r.summary.matches_found ?? "\u2014")}
                    {r.screen_version === "screen_v2" && r.summary.base_rate != null && (
                      <span className="ml-1 text-xs text-gray-500">
                        ({(r.summary.base_rate * 100).toFixed(1)}%)
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">
                    {r.screen_version === "screen_v2"
                      ? (r.summary.total_observations ?? "\u2014")
                      : (r.summary.total_screened ?? "\u2014")}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{fmtDate(r.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/screener/${r.id}`}
                      className="text-xs text-gray-500 hover:text-white"
                    >
                      View
                    </Link>
                  </td>
                </tr>
              ))}
              {results.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-600">
                    No screens run yet. Configure and run your first screen above.
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
