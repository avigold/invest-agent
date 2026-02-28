const STATUS_STYLES: Record<string, string> = {
  queued: "bg-yellow-900/50 text-yellow-300 border-yellow-700",
  running: "bg-blue-900/50 text-blue-300 border-blue-700",
  done: "bg-green-900/50 text-green-300 border-green-700",
  failed: "bg-red-900/50 text-red-300 border-red-700",
  cancelled: "bg-gray-800 text-gray-400 border-gray-600",
};

export default function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.cancelled;
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${style}`}
    >
      {status === "running" && (
        <span className="mr-1.5 h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
      )}
      {status}
    </span>
  );
}
