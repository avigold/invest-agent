"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import JobsTable, { JobRow } from "@/components/JobsTable";

export default function JobsPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  const loadJobs = () => {
    apiJson<JobRow[]>("/api/jobs")
      .then(setJobs)
      .catch(() => {});
  };

  useEffect(() => {
    if (user) loadJobs();
  }, [user]);

  // Poll for updates when there are running/queued jobs
  useEffect(() => {
    const hasActive = jobs.some(
      (j) => j.status === "running" || j.status === "queued"
    );
    if (!hasActive) return;
    const id = setInterval(loadJobs, 3000);
    return () => clearInterval(id);
  }, [jobs]);

  const submitEchoJob = async () => {
    setSubmitting(true);
    setError("");
    try {
      await apiJson("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "echo",
          params: { message: "Hello from Invest Agent" },
        }),
      });
      loadJobs();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to submit job");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading || !user) return null;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Jobs</h1>
        <button
          onClick={submitEchoJob}
          disabled={submitting}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {submitting ? "Submitting..." : "Run echo job"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="rounded-lg border border-gray-800 bg-gray-900">
        <JobsTable jobs={jobs} />
      </div>
    </div>
  );
}
