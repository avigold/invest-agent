import { usePeerValuation, type PeerMetric } from "@/lib/queries";

// ── Formatting ──────────────────────────────────────────────────────

function fmtValue(value: number, format: "multiple" | "pct"): string {
  if (format === "multiple") return `${value.toFixed(1)}x`;
  const pct = value * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

// ── Dot colouring ───────────────────────────────────────────────────

const LOWER_IS_BETTER = new Set(["pe_ratio", "pb_ratio", "debt_equity"]);

function dotColour(percentile: number | null, metricKey: string): string {
  if (percentile == null) return "#6b7280";
  const inverted = LOWER_IS_BETTER.has(metricKey);
  const effective = inverted ? 100 - percentile : percentile;
  if (effective >= 60) return "#4ade80"; // green
  if (effective >= 40) return "#facc15"; // yellow
  return "#f87171"; // red
}

function dotTextColour(percentile: number | null, metricKey: string): string {
  if (percentile == null) return "text-gray-500";
  const inverted = LOWER_IS_BETTER.has(metricKey);
  const effective = inverted ? 100 - percentile : percentile;
  if (effective >= 60) return "text-green-400";
  if (effective >= 40) return "text-yellow-400";
  return "text-red-400";
}

// ── Dot-on-Range Bar ────────────────────────────────────────────────

function DotOnRange({ metric }: { metric: PeerMetric }) {
  const { stats, company_value, percentile_rank, key } = metric;
  const range = stats.p90 - stats.p10;
  if (range === 0) return <div className="h-6 w-full" />;

  const pct = (v: number) =>
    Math.max(0, Math.min(100, ((v - stats.p10) / range) * 100));

  const boxLeft = pct(stats.p25);
  const boxWidth = pct(stats.p75) - boxLeft;
  const medianPos = pct(stats.p50);
  const dotPos = company_value != null ? pct(company_value) : null;

  return (
    <div className="relative h-6 w-full">
      {/* Whisker line p10–p90 */}
      <div
        className="absolute top-1/2 h-px bg-gray-600"
        style={{ left: 0, right: 0, transform: "translateY(-50%)" }}
      />
      {/* IQR box p25–p75 */}
      <div
        className="absolute top-1/2 h-3 rounded-sm bg-gray-700/80"
        style={{
          left: `${boxLeft}%`,
          width: `${boxWidth}%`,
          transform: "translateY(-50%)",
        }}
      />
      {/* Median tick */}
      <div
        className="absolute top-1/2 h-4 w-0.5 bg-gray-400"
        style={{
          left: `${medianPos}%`,
          transform: "translate(-50%, -50%)",
        }}
      />
      {/* Company dot */}
      {dotPos != null && (
        <div
          className="absolute top-1/2 h-3 w-3 rounded-full border-2 border-white/80"
          style={{
            left: `${dotPos}%`,
            transform: "translate(-50%, -50%)",
            backgroundColor: dotColour(percentile_rank, key),
          }}
        />
      )}
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────────

export default function ValuationVsPeers({ ticker }: { ticker: string }) {
  const { data, isLoading } = usePeerValuation(ticker);

  if (isLoading) {
    return (
      <div className="mb-8 animate-pulse">
        <div className="h-5 w-64 rounded bg-gray-800 mb-3" />
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-8 rounded bg-gray-800/50" />
          ))}
        </div>
      </div>
    );
  }

  if (!data || data.metrics.length === 0) return null;

  return (
    <div className="mb-8">
      <h2 className="mb-1 text-lg font-semibold text-white">
        Valuation vs {data.sector} Peers
      </h2>
      <p className="mb-4 text-xs text-gray-500">
        {data.company_count} companies in sector
      </p>

      <div className="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
        <div className="space-y-3">
          {data.metrics.map((m) => (
            <div key={m.key} className="grid grid-cols-[140px_1fr_100px] md:grid-cols-[160px_1fr_140px] items-center gap-3">
              {/* Label */}
              <div className="text-xs text-gray-400 truncate">{m.label}</div>

              {/* Bar */}
              <DotOnRange metric={m} />

              {/* Value + percentile */}
              <div className="text-right text-xs font-mono">
                {m.company_value != null ? (
                  <>
                    <span className={`font-medium ${dotTextColour(m.percentile_rank, m.key)}`}>
                      {fmtValue(m.company_value, m.format)}
                    </span>
                    {m.percentile_rank != null && (
                      <span className="text-gray-500 ml-1.5">
                        {ordinal(m.percentile_rank)}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-gray-600">N/A</span>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="mt-4 flex items-center gap-4 text-[10px] text-gray-600 border-t border-gray-800 pt-3">
          <span className="flex items-center gap-1">
            <span className="inline-block h-px w-4 bg-gray-600" /> p10–p90
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-4 rounded-sm bg-gray-700/80" /> p25–p75
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-0.5 bg-gray-400" /> median
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-400 border border-white/80" /> company
          </span>
        </div>
      </div>
    </div>
  );
}
