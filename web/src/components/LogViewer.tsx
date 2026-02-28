"use client";

import { useEffect, useRef, useState } from "react";
import { apiJson } from "@/lib/api";

interface LogViewerProps {
  jobId: string;
  status: string;
}

interface JobLogResponse {
  log_text: string | null;
  status: string;
}

export default function LogViewer({ jobId, status }: LogViewerProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [live, setLive] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (status === "queued") {
      setLines(["Waiting in queue..."]);
      setLive(false);
      return;
    }

    // Fetch logs immediately, then poll while running
    let cancelled = false;

    const fetchLogs = async () => {
      try {
        const data = await apiJson<JobLogResponse>(`/api/jobs/${jobId}`);
        if (cancelled) return;
        if (data.log_text) {
          setLines(data.log_text.split("\n"));
        }
        if (data.status === "running") {
          setLive(true);
        } else {
          setLive(false);
        }
      } catch {
        // ignore
      }
    };

    fetchLogs();

    if (status === "running") {
      setLive(true);
      const id = setInterval(fetchLogs, 1000);
      return () => {
        cancelled = true;
        clearInterval(id);
      };
    }

    return () => {
      cancelled = true;
    };
  }, [jobId, status]);

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
