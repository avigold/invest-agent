import { useState } from "react";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { useJobs, queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";
import JobsTable, { JobRow } from "@/components/JobsTable";

export default function Jobs() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: jobs = [] } = useJobs<JobRow[]>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

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
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs() });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to submit job");
    } finally {
      setSubmitting(false);
    }
  };

  const refreshJobs = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.jobs() });
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
        <JobsTable jobs={jobs} onRefresh={refreshJobs} />
      </div>
    </div>
  );
}
