import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { useRecommendations, useScoringProfiles, queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";
import RecommendationTable, {
  RecommendationRow,
} from "@/components/RecommendationTable";
import ScoringProfileModal from "@/components/ScoringProfileModal";
import { exportToCsv, todayStr } from "@/lib/export";

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

interface ProfileSummary {
  id: string;
  name: string;
  is_default: boolean;
}

export default function Recommendations() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [classFilter, setClassFilter] = useState("");
  const [countryFilter, setCountryFilter] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");
  const [page, setPage] = useState(1);
  const [showModal, setShowModal] = useState(false);
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  const [activeProfileName, setActiveProfileName] = useState<string | null>(null);

  // Load scoring profiles to determine default
  const { data: profiles = [] } = useScoringProfiles<ProfileSummary[]>();

  // Set default profile on first load
  useEffect(() => {
    if (profiles.length > 0 && activeProfileId === null) {
      const active = profiles.find((p) => p.is_default);
      if (active) {
        setActiveProfileId(active.id);
        setActiveProfileName(active.name);
      }
    }
  }, [profiles, activeProfileId]);

  const filters: Record<string, string | undefined> = {
    classification: classFilter || undefined,
    country_iso2: countryFilter || undefined,
    gics_code: sectorFilter || undefined,
    profile_id: activeProfileId || undefined,
  };
  const { data: recs = [], isLoading } = useRecommendations<RecommendationRow[]>(filters);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  const handleFlush = () => {
    queryClient.invalidateQueries({ queryKey: ["recommendations"] });
  };

  const handleExport = () => {
    if (!filtered.length) return;
    exportToCsv(`fundamentals_${todayStr()}.csv`,
      ["Rank", "Ticker", "Name", "Country", "Sector", "Composite", "Company", "Country Score", "Industry", "Signal"],
      filtered.map((r) => [r.rank, r.ticker, r.name, r.country_iso2, r.gics_code, r.composite_score, r.company_score, r.country_score, r.industry_score, r.classification]),
    );
  };

  const handleProfileChange = (profileId: string | null) => {
    if (profileId) {
      setActiveProfileId(profileId);
      const p = profiles.find((pr) => pr.id === profileId);
      setActiveProfileName(p?.name || null);
    } else {
      setActiveProfileId(null);
      setActiveProfileName(null);
    }
  };

  // Reset page when filters or search change
  useEffect(() => {
    setPage(1);
  }, [search, classFilter, countryFilter, sectorFilter]);

  const totalCount = recs.length;
  const q = search.toLowerCase();
  const filtered = q
    ? recs.filter(
        (r) =>
          r.ticker.toLowerCase().includes(q) ||
          r.name.toLowerCase().includes(q),
      )
    : recs;

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visible = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  if (loading || !user) return null;

  const buys = filtered.filter((r) => r.classification === "Buy").length;
  const holds = filtered.filter((r) => r.classification === "Hold").length;
  const sells = filtered.filter((r) => r.classification === "Sell").length;

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">
            Fundamentals
            {!isLoading && totalCount > 0 && (
              <span className="ml-2 text-base font-normal text-gray-500">
                {q
                  ? `${filtered.length} of ${totalCount}`
                  : `${totalCount}`}
              </span>
            )}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {activeProfileName
              ? `Custom profile: ${activeProfileName}`
              : "Composite scores: 20% country + 20% industry + 60% company"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {filtered.length > 0 && (
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
          onClick={() => setShowModal(true)}
          className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
            activeProfileId
              ? "border-blue-700/50 bg-blue-950/30 text-blue-400 hover:bg-blue-950/50"
              : "border-gray-700 bg-gray-800 text-gray-400 hover:bg-gray-700"
          }`}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          {activeProfileName || "Default"}
        </button>
        </div>
      </div>

      {!isLoading && recs.length > 0 && (
        <div className="mb-6 grid grid-cols-3 gap-4">
          <div className="rounded-lg border border-green-800/50 bg-green-950/20 p-4">
            <div className="text-xs uppercase text-green-500">Buy</div>
            <div className="text-3xl font-bold text-green-400">{buys}</div>
          </div>
          <div className="rounded-lg border border-yellow-800/50 bg-yellow-950/20 p-4">
            <div className="text-xs uppercase text-yellow-500">Hold</div>
            <div className="text-3xl font-bold text-yellow-400">{holds}</div>
          </div>
          <div className="rounded-lg border border-red-800/50 bg-red-950/20 p-4">
            <div className="text-xs uppercase text-red-500">Sell</div>
            <div className="text-3xl font-bold text-red-400">{sells}</div>
          </div>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
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
          value={classFilter}
          onChange={(e) => setClassFilter(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 sm:flex-none"
        >
          <option value="">All signals</option>
          <option value="Buy">Buy</option>
          <option value="Hold">Hold</option>
          <option value="Sell">Sell</option>
        </select>
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

      <div className="rounded-lg border border-gray-800 bg-gray-900">
        {isLoading ? (
          <div className="flex items-center justify-center p-12">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
            <span className="ml-3 text-sm text-gray-500">Loading fundamentals...</span>
          </div>
        ) : (
          <RecommendationTable recommendations={visible} />
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

      <ScoringProfileModal
        open={showModal}
        onClose={() => setShowModal(false)}
        onProfileChange={handleProfileChange}
        activeProfileId={activeProfileId}
      />
    </div>
  );
}
