import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { readCache, writeCache, clearCache } from "@/lib/cache";
import IndustryTable, { IndustryRow } from "@/components/IndustryTable";

export default function Industries() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const [industries, setIndustries] = useState<IndustryRow[] | null>(null);
  const [countryFilter, setCountryFilter] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [flushKey, setFlushKey] = useState(0);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  useEffect(() => {
    if (!user) return;
    const key = `industries:${countryFilter}`;

    // Try cache first
    const cached = readCache<IndustryRow[]>(key);
    if (cached) {
      setIndustries(cached);
    } else {
      setIndustries(null);
    }

    // Always fetch fresh in background
    const params = countryFilter ? `?iso2=${countryFilter}` : "";
    apiJson<IndustryRow[]>(`/v1/industries${params}`)
      .then((rows) => {
        setIndustries(rows);
        writeCache(key, rows);
      })
      .catch(() => { if (!cached) setIndustries([]); });
  }, [user, countryFilter, flushKey]);

  const handleFlush = useCallback(() => {
    clearCache("industries:");
    setIndustries(null);
    setFlushKey((k) => k + 1);
  }, []);

  const submitRefresh = async () => {
    setSubmitting(true);
    setError("");
    try {
      const result = await apiJson<{ id: string }>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "industry_refresh",
          params: {},
        }),
      });
      navigate(`/jobs/${result.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to submit job");
    } finally {
      setSubmitting(false);
    }
  };

  // Extract unique countries from the data for the filter dropdown
  const countryList = industries
    ? Array.from(
        new Map(
          industries.map((r) => [r.country_iso2, r.country_name])
        ).entries()
      ).sort((a, b) => a[1].localeCompare(b[1]))
    : [];

  const initialLoading = industries === null;

  if (loading || !user) return null;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Industries</h1>
        <div className="flex items-center gap-3">
          <select
            value={countryFilter}
            onChange={(e) => setCountryFilter(e.target.value)}
            className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300"
          >
            <option value="">All countries</option>
            {countryList.map(([iso2, name]) => (
              <option key={iso2} value={iso2}>
                {name}
              </option>
            ))}
          </select>
          <button
            onClick={handleFlush}
            title="Clear cache and reload"
            className="rounded-lg border border-gray-700 bg-gray-800 p-2 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          <button
            onClick={submitRefresh}
            disabled={submitting}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
          >
            {submitting ? "Submitting..." : "Refresh Industries"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="rounded-lg border border-gray-800 bg-gray-900">
        {initialLoading ? (
          <div className="flex items-center justify-center p-12">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
            <span className="ml-3 text-sm text-gray-500">Loading industries...</span>
          </div>
        ) : (
          <IndustryTable industries={industries} />
        )}
      </div>
    </div>
  );
}
