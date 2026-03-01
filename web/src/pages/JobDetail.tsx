import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import LogViewer from "@/components/LogViewer";

interface JobDetailData {
  id: string;
  command: string;
  params: Record<string, unknown>;
  status: string;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  log_text: string | null;
  queue_position: number | null;
}

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const [job, setJob] = useState<JobDetailData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  useEffect(() => {
    if (!user || !id) return;
    apiJson<JobDetailData>(`/api/jobs/${id}`)
      .then(setJob)
      .catch(() => setError("Job not found"));
  }, [user, id]);

  // Poll for status updates
  useEffect(() => {
    if (!job || !["running", "queued"].includes(job.status)) return;
    const interval = setInterval(() => {
      apiJson<JobDetailData>(`/api/jobs/${id}`)
        .then(setJob)
        .catch(() => {});
    }, 3000);
    return () => clearInterval(interval);
  }, [job, id]);

  const handleCancel = async () => {
    try {
      await apiJson(`/api/jobs/${id}/cancel`, { method: "POST" });
      apiJson<JobDetailData>(`/api/jobs/${id}`).then(setJob);
    } catch {
      // ignore
    }
  };

  const handleDelete = async () => {
    try {
      await apiJson(`/api/jobs/${id}`, { method: "DELETE" });
      navigate("/jobs");
    } catch {
      // ignore
    }
  };

  if (loading || !user) return null;

  if (error) {
    return (
      <div className="text-center">
        <p className="text-red-400">{error}</p>
        <Link to="/jobs" className="text-brand hover:underline">
          Back to jobs
        </Link>
      </div>
    );
  }

  if (!job) return <p className="text-gray-500">Loading...</p>;

  return (
    <div>
      <div className="mb-6">
        <Link to="/jobs" className="text-sm text-gray-400 hover:text-white">
          &larr; All jobs
        </Link>
      </div>

      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="mb-2 text-2xl font-bold text-white">{job.command}</h1>
          <div className="flex items-center gap-3">
            <StatusBadge status={job.status} />
            {job.queue_position && (
              <span className="text-sm text-gray-400">
                Queue position: #{job.queue_position}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          {["running", "queued"].includes(job.status) && (
            <button
              onClick={handleCancel}
              className="rounded border border-red-800 px-3 py-1.5 text-sm text-red-400 hover:bg-red-900/30"
            >
              Cancel
            </button>
          )}
          {!["running", "queued"].includes(job.status) && (
            <button
              onClick={handleDelete}
              className="rounded border border-gray-700 px-3 py-1.5 text-sm text-gray-400 hover:bg-gray-800"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      <div className="mb-6 grid grid-cols-3 gap-4 rounded-lg border border-gray-800 bg-gray-900 p-4 text-sm">
        <div>
          <span className="text-gray-400">Queued</span>
          <p className="text-white">
            {new Date(job.queued_at).toLocaleString()}
          </p>
        </div>
        <div>
          <span className="text-gray-400">Started</span>
          <p className="text-white">
            {job.started_at
              ? new Date(job.started_at).toLocaleString()
              : "\u2014"}
          </p>
        </div>
        <div>
          <span className="text-gray-400">Finished</span>
          <p className="text-white">
            {job.finished_at
              ? new Date(job.finished_at).toLocaleString()
              : "\u2014"}
          </p>
        </div>
      </div>

      {Object.keys(job.params).length > 0 && (
        <div className="mb-6">
          <h2 className="mb-2 text-sm font-medium text-gray-400">Parameters</h2>
          <pre className="rounded-lg border border-gray-800 bg-gray-950 p-4 text-sm text-gray-300">
            {JSON.stringify(job.params, null, 2)}
          </pre>
        </div>
      )}

      <LogViewer jobId={job.id} status={job.status} />
    </div>
  );
}
