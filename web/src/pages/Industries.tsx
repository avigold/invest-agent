import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import IndustryTable, { IndustryRow } from "@/components/IndustryTable";

export default function Industries() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const [industries, setIndustries] = useState<IndustryRow[]>([]);
  const [countryFilter, setCountryFilter] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  const loadIndustries = (iso2?: string) => {
    const params = iso2 ? `?iso2=${iso2}` : "";
    apiJson<IndustryRow[]>(`/v1/industries${params}`)
      .then(setIndustries)
      .catch(() => {});
  };

  useEffect(() => {
    if (user) loadIndustries(countryFilter || undefined);
  }, [user, countryFilter]);

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
  const countries = Array.from(
    new Map(
      industries.map((r) => [r.country_iso2, r.country_name])
    ).entries()
  ).sort((a, b) => a[1].localeCompare(b[1]));

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
            {countries.map(([iso2, name]) => (
              <option key={iso2} value={iso2}>
                {name}
              </option>
            ))}
          </select>
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
        <IndustryTable industries={industries} />
      </div>
    </div>
  );
}
