import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { useCompanies, queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";
import CompanyTable, { CompanyRow } from "@/components/CompanyTable";

const PAGE_SIZE = 25;

const GICS_SECTORS: { code: string; name: string }[] = [
  { code: "10", name: "Energy" },
  { code: "15", name: "Materials" },
  { code: "20", name: "Industrials" },
  { code: "25", name: "Consumer Discretionary" },
  { code: "30", name: "Consumer Staples" },
  { code: "35", name: "Health Care" },
  { code: "40", name: "Financials" },
  { code: "45", name: "Information Technology" },
  { code: "50", name: "Communication Services" },
  { code: "55", name: "Utilities" },
  { code: "60", name: "Real Estate" },
];

const COUNTRIES: { code: string; name: string }[] = [
  { code: "US", name: "United States" },
  { code: "GB", name: "United Kingdom" },
  { code: "JP", name: "Japan" },
  { code: "CA", name: "Canada" },
  { code: "AU", name: "Australia" },
  { code: "DE", name: "Germany" },
  { code: "FR", name: "France" },
  { code: "CH", name: "Switzerland" },
  { code: "SE", name: "Sweden" },
  { code: "NL", name: "Netherlands" },
];

export default function Companies() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");
  const [countryFilter, setCountryFilter] = useState("");
  const [page, setPage] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const filters = {
    gics_code: sectorFilter || undefined,
    country_iso2: countryFilter || undefined,
  };
  const { data: companies = [], isLoading } = useCompanies<CompanyRow[]>(filters);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  const handleFlush = () => {
    queryClient.invalidateQueries({ queryKey: ["companies"] });
  };

  const submitRefresh = async () => {
    setSubmitting(true);
    setError("");
    try {
      const result = await apiJson<{ id: string }>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "company_refresh",
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

  // Reset page when filters or search change
  useEffect(() => {
    setPage(1);
  }, [search, sectorFilter, countryFilter]);

  const totalCount = companies.length;
  const q = search.toLowerCase();
  const filtered = q
    ? companies.filter(
        (c) =>
          c.ticker.toLowerCase().includes(q) ||
          c.name.toLowerCase().includes(q),
      )
    : companies;

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visible = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  if (loading || !user) return null;

  return (
    <div>
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold text-white">
            Companies
            {!isLoading && (
              <span className="ml-2 text-base font-normal text-gray-500">
                {q
                  ? `${filtered.length} of ${totalCount}`
                  : `${totalCount}`}
              </span>
            )}
          </h1>
          <div className="flex items-center gap-2">
            <button
              onClick={handleFlush}
              title="Clear cache and reload"
              className="rounded-lg border border-gray-700 bg-gray-800 p-2 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
            <Link
              to="/companies/add"
              className="rounded-lg border border-gray-700 bg-gray-800 px-4 py-2 text-sm font-medium text-gray-300 hover:bg-gray-700"
            >
              + Add
            </Link>
            <button
              onClick={submitRefresh}
              disabled={submitting}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
            >
              {submitting ? "Submitting..." : "Refresh"}
            </button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-0 flex-1 sm:flex-none sm:w-52">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or ticker..."
              className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 pr-8 text-sm text-gray-300 placeholder-gray-500"
            />
          </div>
          <select
            value={countryFilter}
            onChange={(e) => setCountryFilter(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 sm:flex-none"
          >
            <option value="">All countries</option>
            {COUNTRIES.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            value={sectorFilter}
            onChange={(e) => setSectorFilter(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 sm:flex-none"
          >
            <option value="">All sectors</option>
            {GICS_SECTORS.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
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
            <span className="ml-3 text-sm text-gray-500">Loading companies...</span>
          </div>
        ) : (
          <CompanyTable companies={visible} />
        )}
      </div>

      {!isLoading && totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <span className="text-gray-500">
            {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} of {filtered.length}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(safePage - 1)}
              disabled={safePage <= 1}
              className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Prev
            </button>
            <span className="text-gray-400">
              Page {safePage} of {totalPages}
            </span>
            <button
              onClick={() => setPage(safePage + 1)}
              disabled={safePage >= totalPages}
              className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
