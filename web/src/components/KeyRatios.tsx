interface KeyRatiosProps {
  ratios: Record<string, number | null>;
  marketCap?: number | null;
}

interface RatioConfig {
  label: string;
  format: (v: number) => string;
  colour?: (v: number) => string;
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function pctSigned(v: number): string {
  const s = (v * 100).toFixed(1);
  return v > 0 ? `+${s}%` : `${s}%`;
}

function multiple(v: number): string {
  return `${v.toFixed(1)}x`;
}

function valuation(v: number): string {
  return `${v.toFixed(1)}x`;
}

function fmtCap(v: number): string {
  if (v >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toLocaleString()}`;
}

const profitColour = (v: number) =>
  v > 0 ? "text-green-400" : v < 0 ? "text-red-400" : "text-gray-400";

const growthColour = (v: number) =>
  v > 0.05 ? "text-green-400" : v < -0.05 ? "text-red-400" : "text-gray-400";

const leverageColour = (v: number) =>
  v > 3 ? "text-red-400" : v > 2 ? "text-yellow-400" : "text-green-400";

const RATIO_CONFIGS: { category: string; keys: [string, RatioConfig][] }[] = [
  {
    category: "Valuation",
    keys: [
      ["pe_ratio", { label: "P/E Ratio", format: valuation }],
      ["pb_ratio", { label: "P/B Ratio", format: valuation }],
      ["_market_cap", { label: "Market Cap", format: fmtCap }],
    ],
  },
  {
    category: "Profitability",
    keys: [
      ["roe", { label: "ROE", format: pct, colour: profitColour }],
      ["net_margin", { label: "Net Margin", format: pct, colour: profitColour }],
      ["gross_margin", { label: "Gross Margin", format: pct }],
      ["operating_margin", { label: "Operating Margin", format: pct, colour: profitColour }],
    ],
  },
  {
    category: "Growth",
    keys: [
      ["revenue_growth", { label: "Revenue Growth", format: pctSigned, colour: growthColour }],
      ["eps_growth", { label: "EPS Growth", format: pctSigned, colour: growthColour }],
    ],
  },
  {
    category: "Risk & Capital",
    keys: [
      ["debt_equity", { label: "Debt / Equity", format: multiple, colour: leverageColour }],
      ["current_ratio", { label: "Current Ratio", format: multiple }],
      ["fcf_yield", { label: "FCF Yield", format: pct, colour: profitColour }],
    ],
  },
];

export default function KeyRatios({ ratios, marketCap }: KeyRatiosProps) {
  // Merge market cap into ratios for unified rendering
  const all: Record<string, number | null> = { ...ratios };
  if (marketCap != null) all["_market_cap"] = marketCap;

  // Check if we have any data to show
  const hasAny = RATIO_CONFIGS.some((cat) =>
    cat.keys.some(([k]) => all[k] != null)
  );
  if (!hasAny) return null;

  return (
    <div className="mb-8">
      <h2 className="mb-3 text-lg font-semibold text-white">Key Ratios</h2>
      <div className="space-y-4">
        {RATIO_CONFIGS.map((cat) => {
          const visible = cat.keys.filter(([k]) => all[k] != null);
          if (visible.length === 0) return null;
          return (
            <div key={cat.category}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
                {cat.category}
              </h3>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
                {visible.map(([key, cfg]) => {
                  const v = all[key]!;
                  const colourClass = cfg.colour ? cfg.colour(v) : "text-white";
                  return (
                    <div
                      key={key}
                      className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-3"
                    >
                      <div className="text-xs text-gray-500">{cfg.label}</div>
                      <div className={`mt-1 text-lg font-semibold font-mono ${colourClass}`}>
                        {cfg.format(v)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
