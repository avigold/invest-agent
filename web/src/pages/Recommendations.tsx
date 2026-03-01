import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import RecommendationTable, {
  RecommendationRow,
} from "@/components/RecommendationTable";
import ScoringProfileModal from "@/components/ScoringProfileModal";

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
  const [recommendations, setRecommendations] = useState<RecommendationRow[]>(
    []
  );
  const [search, setSearch] = useState("");
  const [classFilter, setClassFilter] = useState("");
  const [countryFilter, setCountryFilter] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  const [activeProfileName, setActiveProfileName] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  // Load active profile on mount
  useEffect(() => {
    if (!user) return;
    apiJson<ProfileSummary[]>("/v1/scoring-profiles")
      .then((profiles) => {
        const active = profiles.find((p) => p.is_default);
        if (active) {
          setActiveProfileId(active.id);
          setActiveProfileName(active.name);
        } else {
          setActiveProfileId(null);
          setActiveProfileName(null);
        }
      })
      .catch(() => {});
  }, [user]);

  const loadRecommendations = useCallback(
    (
      classification?: string,
      countryIso2?: string,
      gicsCode?: string,
      profileId?: string | null,
    ) => {
      const params = new URLSearchParams();
      if (classification) params.set("classification", classification);
      if (countryIso2) params.set("country_iso2", countryIso2);
      if (gicsCode) params.set("gics_code", gicsCode);
      if (profileId) params.set("profile_id", profileId);
      const qs = params.toString();
      apiJson<RecommendationRow[]>(`/v1/recommendations${qs ? `?${qs}` : ""}`)
        .then(setRecommendations)
        .catch(() => {});
    },
    [],
  );

  useEffect(() => {
    if (user)
      loadRecommendations(
        classFilter || undefined,
        countryFilter || undefined,
        sectorFilter || undefined,
        activeProfileId,
      );
  }, [user, classFilter, countryFilter, sectorFilter, activeProfileId, loadRecommendations]);

  const handleProfileChange = (profileId: string | null) => {
    if (profileId) {
      setActiveProfileId(profileId);
      // Refresh profile name
      apiJson<ProfileSummary[]>("/v1/scoring-profiles")
        .then((profiles) => {
          const p = profiles.find((pr) => pr.id === profileId);
          setActiveProfileName(p?.name || null);
        })
        .catch(() => {});
    } else {
      setActiveProfileId(null);
      setActiveProfileName(null);
    }
  };

  const q = search.toLowerCase();
  const filtered = q
    ? recommendations.filter(
        (r) =>
          r.ticker.toLowerCase().includes(q) ||
          r.name.toLowerCase().includes(q),
      )
    : recommendations;

  if (loading || !user) return null;

  const buys = filtered.filter((r) => r.classification === "Buy").length;
  const holds = filtered.filter((r) => r.classification === "Hold").length;
  const sells = filtered.filter((r) => r.classification === "Sell").length;

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Recommendations</h1>
          <p className="mt-1 text-sm text-gray-500">
            {activeProfileName
              ? `Custom profile: ${activeProfileName}`
              : "Composite scores: 20% country + 20% industry + 60% company"}
          </p>
        </div>
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

      {recommendations.length > 0 && (
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

      <div className="mb-4 flex flex-wrap gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name or ticker..."
          className="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 placeholder-gray-500 sm:flex-none sm:w-52"
        />
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
        <RecommendationTable recommendations={filtered} />
      </div>

      <ScoringProfileModal
        open={showModal}
        onClose={() => setShowModal(false)}
        onProfileChange={handleProfileChange}
        activeProfileId={activeProfileId}
      />
    </div>
  );
}
