"use client";

import { useEffect, useRef, useState } from "react";

interface LogViewerProps {
  jobId: string;
  status: string;
}

export default function LogViewer({ jobId, status }: LogViewerProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const es = new EventSource(`/api/jobs/${jobId}/stream`, {
      withCredentials: true,
    });

    es.onopen = () => setConnected(true);

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.line) {
          setLines((prev) => [...prev, data.line]);
        }
      } catch {
        // ignore parse errors
      }
    };

    es.addEventListener("done", () => {
      setConnected(false);
      es.close();
    });

    es.addEventListener("queued", () => {
      setLines(["Waiting in queue..."]);
      es.close();
    });

    es.onerror = () => {
      setConnected(false);
      es.close();
    };

    return () => {
      es.close();
    };
  }, [jobId]);

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
        {connected && (
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
