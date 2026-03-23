import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import {
  useWatchlist,
  useRemoveFromWatchlist,
  useReorderWatchlist,
  WatchlistItem,
} from "@/lib/queries";
import { exportToCsv, todayStr } from "@/lib/export";

const COUNTRY_CURRENCY_SYMBOL: Record<string, string> = {
  USD: "$", CAD: "C$", GBP: "\u00a3", AUD: "A$", NZD: "NZ$",
  JPY: "\u00a5", KRW: "\u20a9", BRL: "R$", ZAR: "R", SGD: "S$",
  HKD: "HK$", TWD: "NT$", ILS: "\u20aa", NOK: "kr", SEK: "kr",
  DKK: "kr", CHF: "CHF ", EUR: "\u20ac",
};

function sym(currency: string): string {
  return COUNTRY_CURRENCY_SYMBOL[currency] ?? "$";
}

function changeColor(v: number | null): string {
  if (v == null) return "text-gray-500";
  if (v > 0) return "text-green-400";
  if (v < 0) return "text-red-400";
  return "text-gray-400";
}

function scoreColor(v: number | null): string {
  if (v == null) return "text-gray-600";
  if (v >= 60) return "text-green-400";
  if (v >= 40) return "text-yellow-400";
  return "text-red-400";
}

export default function Watchlist() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const { data: items, isLoading, error } = useWatchlist();
  const remove = useRemoveFromWatchlist();
  const reorder = useReorderWatchlist();

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  if (loading || !user) return null;

  const handleExport = () => {
    if (!items?.length) return;
    exportToCsv(`watchlist_${todayStr()}.csv`,
      ["Ticker", "Name", "Country", "Price", "Change %", "Score", "Composite"],
      items.map((i) => [i.ticker, i.name, i.country_iso2, i.latest_price, i.change_1d_pct, i.overall_score, i.composite_score]),
    );
  };

  const moveItem = (index: number, direction: -1 | 1) => {
    if (!items) return;
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= items.length) return;
    const newOrder = items.map((i) => i.id);
    [newOrder[index], newOrder[newIndex]] = [newOrder[newIndex], newOrder[index]];
    reorder.mutate(newOrder);
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Watchlist</h1>
        {items && items.length > 0 && (
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
      </div>

      {isLoading && (
        <div className="flex items-center gap-3 py-12">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-gray-300" />
          <span className="text-sm text-gray-500">Loading...</span>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/30 p-4 text-sm text-red-400">
          Failed to load watchlist.
        </div>
      )}

      {!isLoading && !error && items && items.length === 0 && (
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-8 text-center">
          <p className="text-gray-400">Your watchlist is empty.</p>
          <p className="mt-2 text-sm text-gray-600">
            Visit a stock detail page and click the star to add it here.
          </p>
        </div>
      )}

      {items && items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-800 bg-gray-900">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="px-4 py-3 w-10"></th>
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Country</th>
                <th className="px-4 py-3 text-right">Price</th>
                <th className="px-4 py-3 text-right">Change</th>
                <th className="px-4 py-3 text-right">Score</th>
                <th className="px-4 py-3 text-right">Composite</th>
                <th className="px-4 py-3 w-10"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item: WatchlistItem, idx: number) => (
                <tr key={item.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  {/* Reorder arrows */}
                  <td className="px-2 py-2">
                    <div className="flex flex-col items-center gap-0.5">
                      <button
                        onClick={() => moveItem(idx, -1)}
                        disabled={idx === 0 || reorder.isPending}
                        className="text-gray-600 hover:text-white disabled:opacity-20 disabled:cursor-default"
                      >
                        <svg className="h-3 w-3" fill="none" viewBox="0 0 12 12" stroke="currentColor" strokeWidth={2}>
                          <path d="M2 8l4-4 4 4" />
                        </svg>
                      </button>
                      <button
                        onClick={() => moveItem(idx, 1)}
                        disabled={idx === items.length - 1 || reorder.isPending}
                        className="text-gray-600 hover:text-white disabled:opacity-20 disabled:cursor-default"
                      >
                        <svg className="h-3 w-3" fill="none" viewBox="0 0 12 12" stroke="currentColor" strokeWidth={2}>
                          <path d="M2 4l4 4 4-4" />
                        </svg>
                      </button>
                    </div>
                  </td>

                  {/* Company */}
                  <td className="px-4 py-2">
                    <Link to={`/stocks/${item.ticker}`} className="text-white hover:text-blue-400">
                      {item.name}
                    </Link>
                    <div className="text-xs text-gray-500">{item.ticker}</div>
                  </td>

                  {/* Country */}
                  <td className="px-4 py-2 text-gray-400">{item.country_iso2}</td>

                  {/* Price */}
                  <td className="px-4 py-2 text-right font-mono text-white">
                    {item.latest_price != null
                      ? `${sym(item.currency)}${item.latest_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                      : "\u2014"}
                  </td>

                  {/* Change */}
                  <td className={`px-4 py-2 text-right font-mono ${changeColor(item.change_1d_pct)}`}>
                    {item.change_1d_pct != null
                      ? `${item.change_1d_pct > 0 ? "+" : ""}${(item.change_1d_pct * 100).toFixed(2)}%`
                      : "\u2014"}
                  </td>

                  {/* Score */}
                  <td className={`px-4 py-2 text-right font-mono ${scoreColor(item.overall_score)}`}>
                    {item.overall_score != null ? item.overall_score.toFixed(1) : "\u2014"}
                  </td>

                  {/* Composite */}
                  <td className={`px-4 py-2 text-right font-mono ${scoreColor(item.composite_score)}`}>
                    {item.composite_score != null ? item.composite_score.toFixed(1) : "\u2014"}
                  </td>

                  {/* Remove */}
                  <td className="px-2 py-2">
                    <button
                      onClick={() => remove.mutate(item.ticker)}
                      disabled={remove.isPending}
                      title="Remove from watchlist"
                      className="text-gray-600 hover:text-red-400 disabled:opacity-50"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
