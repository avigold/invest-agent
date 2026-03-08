import { useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { useEffect } from "react";
import { useUser } from "@/lib/auth";
import { useMLStockDetail } from "@/lib/queries";
import ScoreCard from "@/components/ScoreCard";
import StockChart from "@/components/StockChart";

interface Fundamentals {
  classification: string;
  composite_score: number;
  company_score: number;
  fundamental_score: number;
  market_score: number;
  country_score: number;
  industry_score: number;
}

interface MLScoreDetail {
  id: string;
  ticker: string;
  company_name: string;
  country: string;
  sector: string;
  probability: number;
  suggested_weight: number;
  contributing_features: Record<string, { value: number; importance: number }>;
  feature_values: Record<string, number>;
  scored_at: string;
  model_id: string;
  model_version: string;
  fundamentals: Fundamentals | null;
}

// ── Feature categories ──────────────────────────────────────────────────

interface FeatureCategory {
  label: string;
  defaultOpen: boolean;
  match: (key: string) => boolean;
}

const FEATURE_CATEGORIES: FeatureCategory[] = [
  {
    label: "Profitability & Returns",
    defaultOpen: true,
    match: (k) =>
      [
        "roe", "roa", "roic", "net_margin", "gross_margin", "ebitda_margin",
        "operating_margin", "roe_change", "earnings_quality", "accruals_ratio",
        "effective_tax_rate", "margin_expansion", "piotroski_f_score",
      ].includes(k),
  },
  {
    label: "Growth",
    defaultOpen: true,
    match: (k) =>
      [
        "revenue_growth", "net_income_growth", "operating_income_growth",
        "gross_profit_growth", "eps_growth", "fcf_growth",
      ].includes(k),
  },
  {
    label: "Capital Structure",
    defaultOpen: true,
    match: (k) =>
      [
        "debt_equity", "debt_assets", "net_debt_ebitda", "interest_coverage",
        "current_ratio", "cash_ratio", "cash_conversion", "fcf_to_net_income",
        "dividend_payout", "buyback_yield", "capex_to_depreciation",
        "capex_to_revenue", "rd_to_revenue", "sbc_to_revenue",
      ].includes(k),
  },
  {
    label: "Market & Technical",
    defaultOpen: true,
    match: (k) =>
      k.startsWith("momentum_") || k.startsWith("volatility_") ||
      k.startsWith("max_dd_") || k.startsWith("price_range_") ||
      k.startsWith("distance_from_") || k.startsWith("ma_spread_") ||
      k.startsWith("up_months_ratio") || k.startsWith("avg_daily_volume") ||
      k.startsWith("dollar_volume") || k === "vol_trend",
  },
  {
    label: "Turnover",
    defaultOpen: true,
    match: (k) =>
      ["inventory_turnover", "asset_turnover", "receivables_turnover"].includes(k),
  },
  {
    label: "Balance Sheet",
    defaultOpen: false,
    match: (k) => k.startsWith("bal_"),
  },
  {
    label: "Income Statement",
    defaultOpen: false,
    match: (k) => k.startsWith("inc_"),
  },
  {
    label: "Cash Flow",
    defaultOpen: false,
    match: (k) => k.startsWith("cf_"),
  },
];

// ── Formatting helpers ──────────────────────────────────────────────────

const RATIO_KEYS = new Set([
  "roe", "roa", "roic", "net_margin", "gross_margin", "ebitda_margin",
  "operating_margin", "effective_tax_rate", "revenue_growth",
  "net_income_growth", "operating_income_growth", "gross_profit_growth",
  "eps_growth", "fcf_growth", "debt_equity", "debt_assets",
  "dividend_payout", "buyback_yield", "cash_conversion", "fcf_to_net_income",
  "capex_to_depreciation", "capex_to_revenue", "rd_to_revenue",
  "sbc_to_revenue", "roe_change", "margin_expansion", "accruals_ratio",
  "earnings_quality",
]);

const MOMENTUM_KEYS = new Set([
  "momentum_3m", "momentum_6m", "momentum_12m", "momentum_24m",
  "volatility_3m", "volatility_6m", "volatility_12m",
  "max_dd_12m", "max_dd_24m", "up_months_ratio_12m",
  "price_range_12m", "distance_from_52w_high", "distance_from_52w_low",
  "ma_spread_10", "ma_spread_20", "vol_trend", "momentum_accel",
]);

function humanise(key: string): string {
  let s = key;
  if (s.startsWith("bal_")) s = s.slice(4);
  else if (s.startsWith("inc_")) s = s.slice(4);
  else if (s.startsWith("cf_")) s = s.slice(3);
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtFeatureValue(key: string, value: number): string {
  if (RATIO_KEYS.has(key) || MOMENTUM_KEYS.has(key)) {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (Math.abs(value) >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
  if (Number.isInteger(value)) return value.toLocaleString();
  return value.toFixed(4);
}

function probColor(p: number): string {
  if (p >= 0.6) return "text-green-400";
  if (p >= 0.45) return "text-yellow-400";
  return "text-red-400";
}

function classificationColor(c: string): string {
  if (c === "Buy") return "border-green-700 bg-green-950/30 text-green-400";
  if (c === "Hold") return "border-yellow-700 bg-yellow-950/30 text-yellow-400";
  return "border-red-700 bg-red-950/30 text-red-400";
}

// ── Collapsible section ─────────────────────────────────────────────────

function FeatureSection({
  label,
  features,
  defaultOpen,
}: {
  label: string;
  features: [string, number][];
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (features.length === 0) return null;

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-sm font-semibold text-white">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">{features.length}</span>
          <svg
            className={`h-4 w-4 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>
      {open && (
        <div className="border-t border-gray-800 divide-y divide-gray-800/50">
          {features.map(([key, val]) => {
            const isNeg = val < 0;
            return (
              <div key={key} className="flex items-center justify-between px-4 py-2">
                <span className="text-sm text-gray-400">{humanise(key)}</span>
                <span className={`font-mono text-sm ${isNeg ? "text-red-400" : "text-white"}`}>
                  {fmtFeatureValue(key, val)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Page component ──────────────────────────────────────────────────────

export default function MLStockDetail() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const { ticker: rawTicker } = useParams<{ ticker: string }>();
  const ticker = rawTicker?.toUpperCase() || "";
  const { data, error, isLoading } = useMLStockDetail<MLScoreDetail>(ticker);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  if (loading || !user) return null;

  if (error) {
    return (
      <div>
        <Link to="/ml/picks" className="mb-4 inline-block text-sm text-gray-400 hover:text-white">
          &larr; Back to ML Picks
        </Link>
        <div className="rounded border border-red-800 bg-red-900/30 px-4 py-3 text-red-300">
          {(error as Error).message}
        </div>
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div>
        <Link to="/ml/picks" className="mb-4 inline-block text-sm text-gray-400 hover:text-white">
          &larr; Back to ML Picks
        </Link>
        <div className="flex items-center gap-3 py-12">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
          <span className="text-sm text-gray-500">Loading...</span>
        </div>
      </div>
    );
  }

  const bothAgree = data.fundamentals?.classification === "Buy" && data.probability >= 0.5;

  // Categorise features
  const featureEntries = Object.entries(data.feature_values || {});
  const categorised = FEATURE_CATEGORIES.map((cat) => ({
    ...cat,
    features: featureEntries.filter(([k]) => cat.match(k)) as [string, number][],
  }));
  // Uncategorised features
  const categorisedKeys = new Set(categorised.flatMap((c) => c.features.map(([k]) => k)));
  const uncategorised = featureEntries.filter(
    ([k]) => !categorisedKeys.has(k) && k !== "cat_gics_code" && k !== "cat_country_iso2"
  ) as [string, number][];

  // Top contributing features sorted by importance
  const topFeatures = Object.entries(data.contributing_features)
    .filter(([k]) => k !== "country" && k !== "sector")
    .sort((a, b) => b[1].importance - a[1].importance);

  return (
    <div>
      <Link to="/ml/picks" className="mb-6 inline-block text-sm text-gray-400 hover:text-white">
        &larr; ML Picks
      </Link>

      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold text-white">{data.company_name}</h1>
          <span className="rounded bg-gray-800 px-2 py-1 text-sm text-gray-400">{data.ticker}</span>
          {data.suggested_weight > 0 && (
            <span className="rounded-full border border-green-800 bg-green-900/50 px-2 py-0.5 text-xs text-green-300">
              In Portfolio
            </span>
          )}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-4">
          <span className={`text-2xl font-bold ${probColor(data.probability)}`}>
            {(data.probability * 100).toFixed(1)}% probability
          </span>
          <span className="text-sm text-gray-500">
            {data.country} &middot; {data.sector}
          </span>
        </div>

        {/* Agreement badge */}
        {bothAgree && (
          <div className="mt-3 inline-flex items-center gap-2 rounded-lg border border-yellow-700/50 bg-yellow-950/20 px-3 py-1.5">
            <svg className="h-4 w-4 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
              <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
            </svg>
            <span className="text-sm font-medium text-yellow-300">
              Both systems agree — Buy
            </span>
          </div>
        )}

        <div className="mt-2 text-xs text-gray-600">
          Model: {data.model_version} &middot; Scored {new Date(data.scored_at).toLocaleDateString()}
        </div>
      </div>

      {/* Stock chart */}
      <StockChart ticker={data.ticker} />

      {/* ML Score + Contributing Features */}
      <div className="mb-8">
        <h2 className="mb-3 text-lg font-semibold text-white">ML Score</h2>
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
          <div className="mb-4 flex items-center gap-4">
            <div>
              <div className="text-xs uppercase text-gray-500">Probability</div>
              <div className={`text-3xl font-bold ${probColor(data.probability)}`}>
                {(data.probability * 100).toFixed(1)}%
              </div>
            </div>
            <div className="flex-1">
              <div className="h-3 w-full rounded-full bg-gray-700">
                <div
                  className={`h-3 rounded-full ${data.probability >= 0.6 ? "bg-green-500" : data.probability >= 0.45 ? "bg-yellow-500" : "bg-red-500"}`}
                  style={{ width: `${Math.min(100, data.probability * 100)}%` }}
                />
              </div>
            </div>
          </div>

          {topFeatures.length > 0 && (
            <div>
              <div className="mb-2 text-xs uppercase text-gray-500">Top Contributing Features</div>
              <div className="space-y-2">
                {topFeatures.map(([feat, d]) => (
                  <div key={feat} className="flex items-center gap-3">
                    <span className="w-40 truncate text-sm text-gray-400">{humanise(feat)}</span>
                    <div className="flex-1">
                      <div className="h-2 rounded-full bg-gray-700">
                        <div
                          className="h-2 rounded-full bg-blue-500"
                          style={{ width: `${Math.min(100, d.importance * 100 * 5)}%` }}
                        />
                      </div>
                    </div>
                    <span className="w-16 text-right font-mono text-xs text-gray-400">
                      {(d.importance * 100).toFixed(1)}%
                    </span>
                    <span className="w-20 text-right font-mono text-xs text-gray-500">
                      {fmtFeatureValue(feat, d.value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Deterministic Scores */}
      <div className="mb-8">
        <h2 className="mb-3 text-lg font-semibold text-white">Fundamentals Score</h2>
        {data.fundamentals ? (
          <div>
            <div className="mb-3 flex items-center gap-3">
              <span className={`rounded-lg border px-3 py-1 text-sm font-semibold ${classificationColor(data.fundamentals.classification)}`}>
                {data.fundamentals.classification}
              </span>
              <span className="text-sm text-gray-500">
                Composite: {data.fundamentals.composite_score.toFixed(1)}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              <ScoreCard label="Company" score={data.fundamentals.company_score} />
              <ScoreCard label="Country" score={data.fundamentals.country_score} />
              <ScoreCard label="Industry" score={data.fundamentals.industry_score} />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-4">
              <ScoreCard label="Fundamental" score={data.fundamentals.fundamental_score} />
              <ScoreCard label="Market" score={data.fundamentals.market_score} />
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-800 bg-gray-900/50 px-4 py-6 text-center text-sm text-gray-500">
            Not scored by Fundamentals system
          </div>
        )}
      </div>

      {/* Feature Values by Category */}
      <div className="mb-8">
        <h2 className="mb-3 text-lg font-semibold text-white">
          All Features
          <span className="ml-2 text-sm font-normal text-gray-500">
            {featureEntries.length}
          </span>
        </h2>
        <div className="space-y-3">
          {categorised.map((cat) => (
            <FeatureSection
              key={cat.label}
              label={cat.label}
              features={cat.features}
              defaultOpen={cat.defaultOpen}
            />
          ))}
          {uncategorised.length > 0 && (
            <FeatureSection
              label="Other"
              features={uncategorised}
              defaultOpen={false}
            />
          )}
        </div>
      </div>
    </div>
  );
}
