import { useWatchlistCheck, useAddToWatchlist, useRemoveFromWatchlist } from "@/lib/queries";

export default function WatchlistButton({ ticker }: { ticker: string }) {
  const { data, isLoading } = useWatchlistCheck(ticker);
  const add = useAddToWatchlist();
  const remove = useRemoveFromWatchlist();

  const inWatchlist = data?.in_watchlist ?? false;
  const busy = add.isPending || remove.isPending;

  const toggle = () => {
    if (busy) return;
    if (inWatchlist) {
      remove.mutate(ticker);
    } else {
      add.mutate(ticker);
    }
  };

  if (isLoading) return null;

  return (
    <button
      onClick={toggle}
      disabled={busy}
      title={inWatchlist ? "Remove from watchlist" : "Add to watchlist"}
      className={`inline-flex items-center justify-center rounded-lg border px-2 py-1.5 transition-colors ${
        inWatchlist
          ? "border-yellow-700 bg-yellow-950/30 text-yellow-400 hover:bg-yellow-950/50"
          : "border-gray-700 bg-gray-800 text-gray-500 hover:border-yellow-700 hover:text-yellow-400"
      } ${busy ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
    >
      <svg
        className="h-5 w-5"
        viewBox="0 0 20 20"
        fill={inWatchlist ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth={inWatchlist ? 0 : 1.5}
      >
        <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
      </svg>
    </button>
  );
}
