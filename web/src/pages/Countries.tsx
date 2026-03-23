import { useState } from "react";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { useCountries, queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";
import CountryTable, { CountryRow } from "@/components/CountryTable";
import { exportToCsv, todayStr } from "@/lib/export";

export default function Countries() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: countries, isLoading } = useCountries<CountryRow[]>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  const handleFlush = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.countries() });
  };

  const handleExport = () => {
    if (!countries?.length) return;
    exportToCsv(`countries_${todayStr()}.csv`,
      ["Rank", "Country", "ISO2", "Overall", "Macro", "Market", "Stability"],
      countries.map((c) => [c.rank, c.name, c.iso2, c.overall_score, c.macro_score, c.market_score, c.stability_score]),
    );
  };

  const submitRefresh = async () => {
    setSubmitting(true);
    setError("");
    try {
      const result = await apiJson<{ id: string }>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "country_refresh",
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

  if (loading || !user) return null;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Countries</h1>
        <div className="flex items-center gap-2">
          {countries && countries.length > 0 && (
            <button
              onClick={handleExport}
              title="Export CSV"
              className="rounded-lg border border-gray-700 bg-gray-800 p-2 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
            </button>
          )}
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
            {submitting ? "Submitting..." : "Refresh Countries"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="rounded-lg border border-gray-800 bg-gray-900">
        {isLoading ? (
          <div className="flex items-center justify-center p-12">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
            <span className="ml-3 text-sm text-gray-500">Loading countries...</span>
          </div>
        ) : (
          <CountryTable countries={countries ?? []} />
        )}
      </div>
    </div>
  );
}
