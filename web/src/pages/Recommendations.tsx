import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import RecommendationTable, {
  RecommendationRow,
} from "@/components/RecommendationTable";

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

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  const loadRecommendations = (
    classification?: string,
    countryIso2?: string,
    gicsCode?: string
  ) => {
    const params = new URLSearchParams();
    if (classification) params.set("classification", classification);
    if (countryIso2) params.set("country_iso2", countryIso2);
    if (gicsCode) params.set("gics_code", gicsCode);
    const qs = params.toString();
    apiJson<RecommendationRow[]>(`/v1/recommendations${qs ? `?${qs}` : ""}`)
      .then(setRecommendations)
      .catch(() => {});
  };

  useEffect(() => {
    if (user)
      loadRecommendations(
        classFilter || undefined,
        countryFilter || undefined,
        sectorFilter || undefined
      );
  }, [user, classFilter, countryFilter, sectorFilter]);

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
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Recommendations</h1>
        <p className="mt-1 text-sm text-gray-500">
          Composite scores: 20% country + 20% industry + 60% company
        </p>
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

      <div className="mb-4 flex items-center gap-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name or ticker..."
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 placeholder-gray-500 w-52"
        />
        <select
          value={classFilter}
          onChange={(e) => setClassFilter(e.target.value)}
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300"
        >
          <option value="">All signals</option>
          <option value="Buy">Buy</option>
          <option value="Hold">Hold</option>
          <option value="Sell">Sell</option>
        </select>
        <select
          value={countryFilter}
          onChange={(e) => setCountryFilter(e.target.value)}
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300"
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
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300"
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
    </div>
  );
}
