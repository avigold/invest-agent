import { useEffect, useRef } from "react";
import { useJobLogs } from "@/lib/queries";

interface LogViewerProps {
  jobId: string;
  status: string;
}

export default function LogViewer({ jobId, status }: LogViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { data } = useJobLogs(jobId, status);

  const lines =
    status === "queued"
      ? ["Waiting in queue..."]
      : data?.log_text?.split("\n") ?? [];
  const live = data?.status === "running";

  // Auto-scroll to bottom
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [lines]);

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950">
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-2">
        <span className="text-xs font-medium text-gray-400">Output</span>
        {live && (
          <span className="flex items-center gap-1.5 text-xs text-green-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-400" />
            Live
          </span>
        )}
      </div>
      <div
        ref={containerRef}
        className="max-h-96 overflow-y-auto p-4 font-mono text-sm leading-relaxed"
      >
        {lines.length === 0 ? (
          <span className="text-gray-600">No output yet...</span>
        ) : (
          lines.map((line, i) => (
            <div key={i} className="text-gray-300">
              {line}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
