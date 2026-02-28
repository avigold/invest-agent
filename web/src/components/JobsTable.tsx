"use client";

import Link from "next/link";
import StatusBadge from "./StatusBadge";

export interface JobRow {
  id: string;
  command: string;
  params: Record<string, unknown>;
  status: string;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

function duration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const sec = Math.round((e - s) / 1000);
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s`;
}

export default function JobsTable({ jobs }: { jobs: JobRow[] }) {
  if (jobs.length === 0) {
    return (
      <p className="py-12 text-center text-gray-500">
        No jobs yet. Submit one to get started.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 text-left text-gray-400">
            <th className="px-4 py-3 font-medium">Command</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Queued</th>
            <th className="px-4 py-3 font-medium">Duration</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr
              key={job.id}
              className="border-b border-gray-800/50 hover:bg-gray-900/50"
            >
              <td className="px-4 py-3">
                <Link
                  href={`/jobs/${job.id}`}
                  className="text-brand hover:underline"
                >
                  {job.command}
                </Link>
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={job.status} />
              </td>
              <td className="px-4 py-3 text-gray-400">
                {formatTime(job.queued_at)}
              </td>
              <td className="px-4 py-3 text-gray-400">
                {duration(job.started_at, job.finished_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
