interface MarketStatusData {
  is_open: boolean;
  exchange: string;
  next_open: string;
  last_close_time: string;
}

export default function MarketStatus({ status }: { status: MarketStatusData }) {
  if (status.is_open) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-green-400">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
        </span>
        Market Open
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-gray-500">
      <span className="h-2 w-2 rounded-full bg-gray-600" />
      Market Closed
    </span>
  );
}

export type { MarketStatusData };
