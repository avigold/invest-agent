import { useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { useEffect } from "react";
import { useUser } from "@/lib/auth";
import { useCompanyDetail, useMLStockDetail } from "@/lib/queries";
import ScoreCard from "@/components/ScoreCard";
import StockChart from "@/components/StockChart";
import KeyRatios from "@/components/KeyRatios";
import ValuationVsPeers from "@/components/ValuationVsPeers";
import WatchlistButton from "@/components/WatchlistButton";

// ── Types (deterministic) ─────────────────────────────────────────────

interface Risk {
  type: string;
  severity: string;
  description: string;
}

interface Evidence {
  series: string;
  value: number;
  date: string;
  artefact_id: string;
  source: string;
  source_url: string;
}

interface CompanyPacket {
  ticker: string;
  cik: string;
  company_name: string;
  gics_code: string;
  country_iso2: string;
  as_of: string;
  calc_version: string;
  summary_version: string;
  scores: {
    overall: number;
    fundamental: number;
    market: number;
  };
  rank: number;
  rank_total: number;
  component_data: {
    fundamental_ratios?: Record<string, number | null>;
    market_metrics?: Record<string, number | null>;
  };
  risks: Risk[];
  evidence: Evidence[] | null;
}

// ── Types (ML) ────────────────────────────────────────────────────────

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
  key_ratios?: Record<string, number | null>;
  market_cap_usd?: number | null;
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

// ── Currency helpers ────────────────────────────────────────────────────

const COUNTRY_CURRENCY_SYMBOL: Record<string, string> = {
  US: "$", CA: "C$", GB: "£", AU: "A$", NZ: "NZ$",
  JP: "¥", KR: "₩", BR: "R$", ZA: "R", SG: "S$",
  HK: "HK$", TW: "NT$", IL: "₪", NO: "kr", SE: "kr",
  DK: "kr", CH: "CHF ", DE: "€", FR: "€", NL: "€",
  FI: "€", IE: "€", BE: "€", AT: "€",
};

function currencySymbol(iso2: string | undefined): string {
  return COUNTRY_CURRENCY_SYMBOL[iso2 || ""] ?? "$";
}

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

const RATIO_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  roe: { label: "Return on Equity", format: (v) => `${(v * 100).toFixed(1)}%` },
  net_margin: { label: "Net Margin", format: (v) => `${(v * 100).toFixed(1)}%` },
  debt_equity: { label: "Debt / Equity", format: (v) => `${v.toFixed(2)}x` },
  revenue_growth: { label: "Revenue Growth (YoY)", format: (v) => `${(v * 100).toFixed(1)}%` },
  eps_growth: { label: "EPS Growth (YoY)", format: (v) => `${(v * 100).toFixed(1)}%` },
  fcf_yield: { label: "FCF Yield", format: (v) => `${(v * 100).toFixed(1)}%` },
};

const MARKET_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  return_1y: { label: "1-Year Return", format: (v) => `${(v * 100).toFixed(1)}%` },
  max_drawdown: { label: "Max Drawdown (12mo)", format: (v) => `${(v * 100).toFixed(1)}%` },
  ma_spread: { label: "Price vs 200-Day MA", format: (v) => `${(v * 100).toFixed(1)}%` },
};

function humanise(key: string): string {
  let s = key;
  if (s.startsWith("bal_")) s = s.slice(4);
  else if (s.startsWith("inc_")) s = s.slice(4);
  else if (s.startsWith("cf_")) s = s.slice(3);
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtFeatureValue(key: string, value: number, sym = "$"): string {
  if (RATIO_KEYS.has(key) || MOMENTUM_KEYS.has(key)) {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (Math.abs(value) >= 1e9) return `${sym}${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6) return `${sym}${(value / 1e6).toFixed(1)}M`;
  if (Math.abs(value) >= 1e3) return `${sym}${(value / 1e3).toFixed(1)}K`;
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

function scoreColor(score: number): string {
  if (score >= 60) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function severityColor(severity: string): string {
  if (severity === "high") return "border-red-700 bg-red-950/50 text-red-300";
  if (severity === "medium") return "border-yellow-700 bg-yellow-950/50 text-yellow-300";
  return "border-gray-700 bg-gray-800 text-gray-300";
}

function severityDot(severity: string): string {
  if (severity === "high") return "bg-red-400";
  if (severity === "medium") return "bg-yellow-400";
  return "bg-gray-400";
}

function rankColor(rank: number, total: number): string {
  const pct = rank / total;
  if (pct <= 0.3) return "text-green-400";
  if (pct <= 0.7) return "text-yellow-400";
  return "text-red-400";
}

function rankLabel(rank: number, total: number): string {
  if (rank === 1) return "Top ranked";
  if (rank <= Math.ceil(total * 0.3)) return "Upper tier";
  if (rank <= Math.ceil(total * 0.7)) return "Mid tier";
  return "Lower tier";
}

function formatEvidence(series: string, value: number, sym = "$"): string {
  if (series === "equity_close") return `${sym}${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  if (Math.abs(value) >= 1e9) return `${sym}${(value / 1e9).toFixed(1)}B`;
  if (Math.abs(value) >= 1e6) return `${sym}${(value / 1e6).toFixed(1)}M`;
  return value.toFixed(2);
}

// ── Collapsible feature section ─────────────────────────────────────────

function FeatureSection({
  label,
  features,
  defaultOpen,
  sym,
}: {
  label: string;
  features: [string, number][];
  defaultOpen: boolean;
  sym: string;
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
                  {fmtFeatureValue(key, val, sym)}
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

export default function StockDetail() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const { ticker: rawTicker } = useParams<{ ticker: string }>();
  const ticker = rawTicker?.toUpperCase() || "";

  // Fetch both data sources in parallel
  const {
    data: packet,
    error: packetError,
    isLoading: packetLoading,
  } = useCompanyDetail<CompanyPacket>(ticker);
  const {
    data: ml,
    error: mlError,
    isLoading: mlLoading,
  } = useMLStockDetail<MLScoreDetail>(ticker);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  if (loading || !user) return null;

  const anyLoading = packetLoading || mlLoading;
  const hasData = !!packet || !!ml;
  const bothFailed = !packetLoading && !mlLoading && !!packetError && !!mlError;

  // Show spinner until we have at least one data source, or both have settled
  if (!hasData && anyLoading) {
    return (
      <div className="flex items-center gap-3 py-12">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
        <span className="text-sm text-gray-500">Loading...</span>
      </div>
    );
  }

  // If both failed, continue to render — show chart + "no data" note instead of hard error

  // Derive header info from whichever source is available
  const companyName = ml?.company_name || packet?.company_name || ticker;
  const displayTicker = ml?.ticker || packet?.ticker || ticker;
  const cSym = currencySymbol(packet?.country_iso2 || ml?.country);
  const bothAgree =
    ml && ml.fundamentals?.classification === "Buy" && ml.probability >= 0.5;

  // Detect when all fundamental ratios are null (no data, not a real score)
  const hasFundamentals = packet?.component_data?.fundamental_ratios
    ? Object.values(packet.component_data.fundamental_ratios).some((v) => v != null)
    : false;

  // ML feature processing
  const featureEntries = ml ? Object.entries(ml.feature_values || {}) : [];
  const categorised = FEATURE_CATEGORIES.map((cat) => ({
    ...cat,
    features: featureEntries.filter(([k]) => cat.match(k)) as [string, number][],
  }));
  const categorisedKeys = new Set(categorised.flatMap((c) => c.features.map(([k]) => k)));
  const uncategorised = featureEntries.filter(
    ([k]) => !categorisedKeys.has(k) && k !== "cat_gics_code" && k !== "cat_country_iso2",
  ) as [string, number][];
  const topFeatures = ml
    ? Object.entries(ml.contributing_features)
        .filter(([k]) => k !== "country" && k !== "sector")
        .sort((a, b) => b[1].importance - a[1].importance)
    : [];

  return (
    <div>
      <button onClick={() => navigate(-1)} className="mb-6 inline-block text-sm text-gray-400 hover:text-white">
        &larr; Back
      </button>

      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold text-white">{companyName}</h1>
          <span className="rounded bg-gray-800 px-2 py-1 text-sm text-gray-400">{displayTicker}</span>
          <WatchlistButton ticker={displayTicker} />
          <Link
            to={`/compare?tickers=${displayTicker}`}
            className="rounded border border-gray-700 px-2.5 py-1 text-xs text-gray-400 hover:bg-gray-800 hover:text-white transition-colors"
          >
            Compare
          </Link>
          {ml && ml.suggested_weight > 0 && (
            <span className="rounded-full border border-green-800 bg-green-900/50 px-2 py-0.5 text-xs text-green-300">
              In Portfolio
            </span>
          )}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-4">
          {ml && (
            <span className={`text-2xl font-bold ${probColor(ml.probability)}`}>
              {(ml.probability * 100).toFixed(1)}% probability
            </span>
          )}
          {packet && (
            <span className={`text-lg font-semibold ${rankColor(packet.rank, packet.rank_total)}`}>
              #{packet.rank} of {packet.rank_total}
            </span>
          )}
          {packet && (
            <span className="text-sm text-gray-500">
              {rankLabel(packet.rank, packet.rank_total)}
            </span>
          )}
          {ml && (
            <span className="text-sm text-gray-500">
              {ml.country} &middot; {ml.sector}
            </span>
          )}
        </div>

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
      </div>

      {/* Stock chart */}
      <StockChart key={displayTicker} ticker={displayTicker} />

      {/* Key ratios dashboard */}
      {ml?.key_ratios && (
        <KeyRatios ratios={ml.key_ratios} marketCap={ml.market_cap_usd} />
      )}
      {!ml?.key_ratios && packet?.component_data?.fundamental_ratios && (
        <KeyRatios ratios={packet.component_data.fundamental_ratios} />
      )}

      {/* Valuation vs sector peers */}
      <ValuationVsPeers ticker={displayTicker} />

      {/* No scoring data available */}
      {!ml && !packet && (
        <div className="mb-8 rounded-lg border border-gray-800 bg-gray-900 p-6 text-center">
          <p className="text-gray-400">No scoring data available for {ticker}.</p>
          <p className="mt-1 text-sm text-gray-600">
            Run a company refresh or score-universe job to generate scores.
          </p>
        </div>
      )}

      {/* ── ML Score Section ──────────────────────────────────────── */}
      {ml && (
        <div className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white">ML Score</h2>
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
            <div className="mb-4 flex items-center gap-4">
              <div>
                <div className="text-xs uppercase text-gray-500">Probability</div>
                <div className={`text-3xl font-bold ${probColor(ml.probability)}`}>
                  {(ml.probability * 100).toFixed(1)}%
                </div>
              </div>
              <div className="flex-1">
                <div className="h-3 w-full rounded-full bg-gray-700">
                  <div
                    className={`h-3 rounded-full ${ml.probability >= 0.6 ? "bg-green-500" : ml.probability >= 0.45 ? "bg-yellow-500" : "bg-red-500"}`}
                    style={{ width: `${Math.min(100, ml.probability * 100)}%` }}
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
                        {fmtFeatureValue(feat, d.value, cSym)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="mt-2 text-xs text-gray-600">
            Model: {ml.model_version} &middot; Scored {new Date(ml.scored_at).toLocaleDateString()}
          </div>
        </div>
      )}

      {/* ── Deterministic Scores Section ──────────────────────────── */}
      {packet && (
        <div className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white">Fundamentals Score</h2>
          <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-3">
            <ScoreCard label="Overall" score={packet.scores.overall} />
            {hasFundamentals ? (
              <ScoreCard label="Fundamental (60%)" score={packet.scores.fundamental} />
            ) : (
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="text-xs uppercase text-gray-500">Fundamental (60%)</div>
                <div className="mt-1 text-2xl font-bold text-gray-600">N/A</div>
                <div className="text-xs text-gray-600">No data</div>
              </div>
            )}
            <ScoreCard label="Market (40%)" score={packet.scores.market} />
          </div>

          {/* Composite from ML endpoint (has classification + per-layer scores) */}
          {ml?.fundamentals && (
            <div className="mb-4">
              <div className="flex items-center gap-3">
                <span className={`rounded-lg border px-3 py-1 text-sm font-semibold ${classificationColor(ml.fundamentals.classification)}`}>
                  {ml.fundamentals.classification}
                </span>
                <span className="text-sm text-gray-500">
                  Composite: {ml.fundamentals.composite_score.toFixed(1)}
                </span>
              </div>
            </div>
          )}

          {/* Risks */}
          {packet.risks.length > 0 && (
            <div className="mb-4">
              <h3 className="mb-2 text-sm font-semibold text-gray-400">Risks</h3>
              <div className="space-y-2">
                {packet.risks.map((r, i) => (
                  <div key={i} className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${severityColor(r.severity)}`}>
                    <span className={`mt-1.5 h-2 w-2 flex-shrink-0 rounded-full ${severityDot(r.severity)}`} />
                    <div>
                      <span className="text-xs font-semibold uppercase tracking-wide">{r.severity}</span>
                      <p className="mt-0.5 text-sm">{r.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Fundamental ratios + Market metrics */}
          <div className="grid gap-6 md:grid-cols-2">
            {packet.component_data?.fundamental_ratios && Object.keys(packet.component_data.fundamental_ratios).length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-semibold text-gray-400">Fundamental Ratios</h3>
                <div className="rounded-lg border border-gray-800 bg-gray-900">
                  <div className="divide-y divide-gray-800/50">
                    {Object.entries(packet.component_data.fundamental_ratios).map(([key, val]) => {
                      const meta = RATIO_LABELS[key];
                      const isNeg = val != null && val < 0;
                      return (
                        <div key={key} className="flex items-center justify-between px-4 py-2.5">
                          <span className="text-sm text-gray-400">{meta?.label || key.replace(/_/g, " ")}</span>
                          <span className={`font-mono text-sm font-medium ${isNeg ? "text-red-400" : "text-white"}`}>
                            {val != null && meta ? meta.format(val) : val != null ? String(val) : "\u2014"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {packet.component_data?.market_metrics && Object.keys(packet.component_data.market_metrics).length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-semibold text-gray-400">Market Metrics</h3>
                <div className="rounded-lg border border-gray-800 bg-gray-900">
                  <div className="divide-y divide-gray-800/50">
                    {Object.entries(packet.component_data.market_metrics).map(([key, val]) => {
                      const meta = MARKET_LABELS[key];
                      const isNeg = val != null && val < 0;
                      return (
                        <div key={key} className="flex items-center justify-between px-4 py-2.5">
                          <span className="text-sm text-gray-400">{meta?.label || key.replace(/_/g, " ")}</span>
                          <span className={`font-mono text-sm font-medium ${isNeg ? "text-red-400" : "text-white"}`}>
                            {val != null && meta ? meta.format(val) : val != null ? String(val) : "\u2014"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="mt-2 text-xs text-gray-600">
            as of {packet.as_of} &middot; {packet.calc_version} &middot; {packet.summary_version}
          </div>
        </div>
      )}

      {/* ── Fundamentals classification (ML-only, no packet) ─────── */}
      {!packet && ml?.fundamentals && (
        <div className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white">Fundamentals Score</h2>
          <div className="mb-3 flex items-center gap-3">
            <span className={`rounded-lg border px-3 py-1 text-sm font-semibold ${classificationColor(ml.fundamentals.classification)}`}>
              {ml.fundamentals.classification}
            </span>
            <span className="text-sm text-gray-500">
              Composite: {ml.fundamentals.composite_score.toFixed(1)}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <ScoreCard label="Company" score={ml.fundamentals.company_score} />
            <ScoreCard label="Country" score={ml.fundamentals.country_score} />
            <ScoreCard label="Industry" score={ml.fundamentals.industry_score} />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-4">
            <ScoreCard label="Fundamental" score={ml.fundamentals.fundamental_score} />
            <ScoreCard label="Market" score={ml.fundamentals.market_score} />
          </div>
        </div>
      )}

      {/* ── All Features (ML) ────────────────────────────────────── */}
      {ml && featureEntries.length > 0 && (
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
                sym={cSym}
              />
            ))}
            {uncategorised.length > 0 && (
              <FeatureSection
                label="Other"
                features={uncategorised}
                defaultOpen={false}
                sym={cSym}
              />
            )}
          </div>
        </div>
      )}

      {/* ── Evidence Chain (deterministic) ────────────────────────── */}
      {packet?.evidence && packet.evidence.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white">
            Evidence Chain
            <span className="ml-2 text-sm font-normal text-gray-500">
              {packet.evidence.length} data points
            </span>
          </h2>
          <div className="overflow-x-auto rounded-lg border border-gray-800 bg-gray-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-3">Series</th>
                  <th className="px-4 py-3 text-right">Value</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3 text-xs font-normal normal-case text-gray-600">Artefact</th>
                </tr>
              </thead>
              <tbody>
                {packet.evidence.map((e, i) => (
                  <tr key={i} className="border-b border-gray-800/50">
                    <td className="px-4 py-2 text-gray-300">{e.series.replace(/_/g, " ")}</td>
                    <td className="px-4 py-2 text-right font-mono text-white">{formatEvidence(e.series, e.value, cSym)}</td>
                    <td className="px-4 py-2 text-gray-400">{e.date}</td>
                    <td className="px-4 py-2 text-gray-500">{e.source}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-600">{e.artefact_id.substring(0, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
