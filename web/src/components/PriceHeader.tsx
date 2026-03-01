import MarketStatus, { type MarketStatusData } from "./MarketStatus";

interface LatestPrice {
  date: string;
  value: number;
  change_1d: number;
  change_1d_pct: number;
  prev_close: number;
}

interface Props {
  latest: LatestPrice;
  marketStatus: MarketStatusData;
  crosshairPrice: { date: string; value: number } | null;
  currency: string;
}

export default function PriceHeader({ latest, marketStatus, crosshairPrice, currency }: Props) {
  const displayPrice = crosshairPrice?.value ?? latest.value;
  const showChange = !crosshairPrice;
  const isPositive = latest.change_1d >= 0;

  const fmt = (v: number) =>
    v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="mb-4">
      <div className="flex items-baseline gap-3 flex-wrap">
        <span className="text-3xl font-bold text-white tabular-nums">
          {currency === "USD" ? "$" : ""}{fmt(displayPrice)}
        </span>
        {showChange && (
          <span
            className={`text-lg font-semibold tabular-nums ${
              isPositive ? "text-green-400" : "text-red-400"
            }`}
          >
            {isPositive ? "+" : ""}
            {fmt(latest.change_1d)}
            {" "}
            ({isPositive ? "+" : ""}
            {(latest.change_1d_pct * 100).toFixed(2)}%)
          </span>
        )}
        {crosshairPrice && (
          <span className="text-sm text-gray-500">{crosshairPrice.date}</span>
        )}
      </div>
      <div className="mt-1 flex items-center gap-3">
        <MarketStatus status={marketStatus} />
        <span className="text-xs text-gray-600">
          Last updated {latest.date}
        </span>
      </div>
    </div>
  );
}

export type { LatestPrice };
