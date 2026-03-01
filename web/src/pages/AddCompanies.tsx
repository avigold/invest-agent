import { useEffect, useState, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";

interface SearchResult {
  ticker: string;
  name: string;
  cik: string | null;
  country_iso2: string;
  gics_code: string;
  market_cap: number | null;
  already_added: boolean;
}

interface AddResponse {
  added: number;
  skipped: number;
  tickers_added: string[];
  tickers_skipped: string[];
}

export default function AddCompanies() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const [tab, setTab] = useState<"search" | "bulk">("search");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  if (loading || !user) return null;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/companies"
            className="text-gray-400 hover:text-gray-300"
          >
            &larr; Companies
          </Link>
          <h1 className="text-2xl font-bold text-white">Add Companies</h1>
        </div>
      </div>

      <div className="mb-6 flex gap-1 rounded-lg border border-gray-700 bg-gray-800 p-1">
        <button
          onClick={() => setTab("search")}
          className={`rounded-md px-4 py-2 text-sm font-medium transition ${
            tab === "search"
              ? "bg-gray-700 text-white"
              : "text-gray-400 hover:text-gray-300"
          }`}
        >
          Search by Name/Ticker
        </button>
        <button
          onClick={() => setTab("bulk")}
          className={`rounded-md px-4 py-2 text-sm font-medium transition ${
            tab === "bulk"
              ? "bg-gray-700 text-white"
              : "text-gray-400 hover:text-gray-300"
          }`}
        >
          Bulk Add by Market Cap
        </button>
      </div>

      {tab === "search" ? <SearchTab /> : <BulkTab />}
    </div>
  );
}

function SearchTab() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  const [addResult, setAddResult] = useState<AddResponse | null>(null);
  const [error, setError] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setAddResult(null);
    setError("");

    if (query.trim().length === 0) {
      setResults([]);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await apiJson<SearchResult[]>(
          `/v1/companies/search?q=${encodeURIComponent(query.trim())}`
        );
        setResults(data);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  const toggleSelect = (ticker: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(ticker)) next.delete(ticker);
      else next.add(ticker);
      return next;
    });
  };

  const addSelected = async () => {
    const toAdd = results.filter(
      (r) => selected.has(r.ticker) && !r.already_added
    );
    if (toAdd.length === 0) return;

    setAdding(true);
    setError("");
    try {
      const resp = await apiJson<AddResponse>("/v1/companies/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          companies: toAdd.map((r) => ({
            ticker: r.ticker,
            name: r.name,
            cik: r.cik,
            country_iso2: r.country_iso2,
            gics_code: r.gics_code,
          })),
        }),
      });
      setAddResult(resp);
      setSelected(new Set());
      // Mark newly added as already_added in local state
      setResults((prev) =>
        prev.map((r) =>
          resp.tickers_added.includes(r.ticker)
            ? { ...r, already_added: true }
            : r
        )
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to add companies");
    } finally {
      setAdding(false);
    }
  };

  const submitRefresh = async () => {
    try {
      const result = await apiJson<{ id: string }>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: "company_refresh", params: {} }),
      });
      navigate(`/jobs/${result.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to submit refresh");
    }
  };

  return (
    <div>
      <div className="mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by company name or ticker..."
          className="w-full rounded-lg border border-gray-700 bg-gray-800 px-4 py-3 text-white placeholder-gray-500 focus:border-brand focus:outline-none"
          autoFocus
        />
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {addResult && addResult.added > 0 && (
        <div className="mb-4 rounded border border-green-800 bg-green-900/30 px-4 py-3 text-sm text-green-300">
          <p className="font-medium">
            Added {addResult.added} company{addResult.added > 1 ? "ies" : ""}: {addResult.tickers_added.join(", ")}
          </p>
          {addResult.skipped > 0 && (
            <p className="mt-1 text-green-400">
              Skipped {addResult.skipped} (already in system): {addResult.tickers_skipped.join(", ")}
            </p>
          )}
          <button
            onClick={submitRefresh}
            className="mt-3 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark"
          >
            Refresh Companies Now
          </button>
        </div>
      )}

      {searching && (
        <div className="py-8 text-center text-gray-500">Searching...</div>
      )}

      {!searching && results.length > 0 && (
        <>
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm text-gray-400">
              {results.length} result{results.length !== 1 ? "s" : ""}
            </span>
            {selected.size > 0 && (
              <button
                onClick={addSelected}
                disabled={adding}
                className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
              >
                {adding
                  ? "Adding..."
                  : `Add ${selected.size} Selected`}
              </button>
            )}
          </div>

          <div className="rounded-lg border border-gray-800 bg-gray-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-gray-400">
                  <th className="px-4 py-3 w-10"></th>
                  <th className="px-4 py-3">Ticker</th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr
                    key={r.ticker}
                    className={`border-b border-gray-800 last:border-0 ${
                      r.already_added ? "opacity-50" : "hover:bg-gray-800/50"
                    }`}
                  >
                    <td className="px-4 py-3">
                      {!r.already_added && (
                        <input
                          type="checkbox"
                          checked={selected.has(r.ticker)}
                          onChange={() => toggleSelect(r.ticker)}
                          className="rounded border-gray-600 bg-gray-700"
                        />
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-white">
                      {r.ticker}
                    </td>
                    <td className="px-4 py-3 text-gray-300">{r.name}</td>
                    <td className="px-4 py-3">
                      {r.already_added ? (
                        <span className="rounded bg-gray-700 px-2 py-1 text-xs text-gray-400">
                          Already added
                        </span>
                      ) : (
                        <span className="rounded bg-blue-900/50 px-2 py-1 text-xs text-blue-300">
                          Available
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!searching && query.trim().length > 0 && results.length === 0 && (
        <div className="py-8 text-center text-gray-500">
          No companies found for "{query}"
        </div>
      )}
    </div>
  );
}

function BulkTab() {
  const navigate = useNavigate();
  const [count, setCount] = useState(100);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setSubmitting(true);
    setError("");
    try {
      const result = await apiJson<{ id: string }>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "add_companies_by_market_cap",
          params: { count },
        }),
      });
      navigate(`/jobs/${result.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to submit job");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-6">
      <h2 className="mb-2 text-lg font-semibold text-white">
        Add Next Companies by Market Cap
      </h2>
      <p className="mb-6 text-sm text-gray-400">
        Automatically find and add the largest US public companies (by market
        cap) that aren't already in the system. This runs as a background job
        and may take a few minutes.
      </p>

      <div className="mb-6 flex items-center gap-4">
        <label className="text-sm text-gray-300">Number of companies:</label>
        <input
          type="number"
          value={count}
          onChange={(e) =>
            setCount(Math.max(1, Math.min(500, parseInt(e.target.value) || 1)))
          }
          min={1}
          max={500}
          className="w-24 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-brand focus:outline-none"
        />
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <button
        onClick={submit}
        disabled={submitting}
        className="rounded-lg bg-brand px-6 py-3 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
      >
        {submitting
          ? "Submitting..."
          : `Add Next ${count} Companies by Market Cap`}
      </button>
    </div>
  );
}
