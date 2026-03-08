import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { useAdminStats, useAdminUsers, useAdminJobs, queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Stats {
  total_users: number;
  pro_subscribers: number;
  jobs_today: number;
  running: number;
  queued: number;
}

interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: string;
  plan: string;
  sub_plan: string;
  sub_status: string | null;
  job_count: number;
  last_active: string | null;
  created_at: string | null;
}

interface AdminJob {
  id: string;
  command: string;
  status: string;
  params: Record<string, string>;
  user_email: string | null;
  user_name: string | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

const VALID_ROLES = ["user", "admin"];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDate(iso: string | null): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusColor(status: string): string {
  switch (status) {
    case "running": return "bg-blue-950/60 text-blue-400 border-blue-800";
    case "done": return "bg-green-950/60 text-green-400 border-green-800";
    case "failed": return "bg-red-950/60 text-red-400 border-red-800";
    case "queued": return "bg-yellow-950/60 text-yellow-400 border-yellow-800";
    case "cancelled": return "bg-gray-800 text-gray-400 border-gray-700";
    default: return "bg-gray-800 text-gray-400 border-gray-700";
  }
}

function planBadge(plan: string): string {
  return plan === "pro"
    ? "bg-green-950/60 text-green-400 border-green-800"
    : "bg-gray-800 text-gray-500 border-gray-700";
}

function roleBadge(role: string): string {
  return role === "admin"
    ? "bg-purple-950/60 text-purple-400 border-purple-800"
    : "bg-gray-800 text-gray-500 border-gray-700";
}

function jobParamsLabel(job: AdminJob): string {
  const p = job.params || {};
  if (p.ticker) return p.ticker;
  if (p.iso2) return p.iso2;
  if (p.gics_code) return `GICS ${p.gics_code}`;
  const keys = Object.keys(p);
  if (keys.length === 0) return "\u2014";
  return keys.map((k) => `${k}=${p[k]}`).join(", ").slice(0, 40);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Admin() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: stats } = useAdminStats<Stats>();
  const { data: users = [] } = useAdminUsers<AdminUser[]>();
  const { data: jobs = [] } = useAdminJobs<AdminJob[]>();
  const [error, setError] = useState("");

  useEffect(() => {
    if (loading) return;
    if (!user) { navigate("/login", { replace: true }); return; }
    if (user.role !== "admin") { navigate("/dashboard", { replace: true }); return; }
  }, [user, loading, navigate]);

  const setRole = async (userId: string, role: string) => {
    try {
      await apiJson(`/api/admin/users/${userId}/role`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      queryClient.setQueryData<AdminUser[]>(queryKeys.adminUsers(), (prev) =>
        prev?.map((u) =>
          u.id === userId
            ? { ...u, role, plan: role === "admin" ? "pro" : u.sub_plan }
            : u,
        ),
      );
    } catch {
      setError("Failed to update role");
    }
  };

  if (loading || !user || user.role !== "admin") return null;

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-purple-400">Admin Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">investagent.app</p>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 rounded border border-red-800 bg-red-950/30 p-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Stat cards */}
      {stats && (
        <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Total Users" value={stats.total_users} color="text-purple-400" />
          <StatCard label="Pro Subscribers" value={stats.pro_subscribers} color="text-green-400" />
          <StatCard label="Jobs Today" value={stats.jobs_today} color="text-blue-400" />
          <StatCard
            label="Running / Queued"
            value={`${stats.running} / ${stats.queued}`}
            color="text-amber-400"
          />
        </div>
      )}

      {/* Users table */}
      <div className="mb-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Users ({users.length})
        </h2>
        <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Plan</th>
                <th className="px-4 py-3 text-right">Jobs</th>
                <th className="px-4 py-3">Last Active</th>
                <th className="px-4 py-3">Joined</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.id}
                  className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors"
                >
                  <td className="px-4 py-3 font-mono text-gray-200 text-xs">{u.email}</td>
                  <td className="px-4 py-3 text-gray-400">{u.name || "\u2014"}</td>
                  <td className="px-4 py-3">
                    <select
                      value={u.role}
                      onChange={(e) => setRole(u.id, e.target.value)}
                      className="rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-300 focus:border-purple-500 focus:outline-none"
                    >
                      {VALID_ROLES.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-semibold ${planBadge(u.plan)}`}>
                      {u.plan}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-400">{u.job_count}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{fmtDate(u.last_active)}</td>
                  <td className="px-4 py-3 text-xs text-gray-500">{fmtDate(u.created_at)}</td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-600">No users</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Jobs table */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Recent Jobs ({jobs.length})
        </h2>
        <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">Command</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Params</th>
                <th className="px-4 py-3">Queued</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr
                  key={j.id}
                  className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors"
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/jobs/${j.id}`}
                      className="font-mono text-xs text-blue-400 hover:text-blue-300"
                    >
                      {j.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-block rounded bg-gray-800 px-2 py-0.5 text-xs font-mono text-gray-300">
                      {j.command}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-semibold ${statusColor(j.status)}`}>
                      {j.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {j.user_name || j.user_email || j.id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 font-mono">
                    {jobParamsLabel(j)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{fmtDate(j.queued_at)}</td>
                </tr>
              ))}
              {jobs.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-600">No jobs</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number | string;
  color: string;
}) {
  return (
    <div className="rounded-xl border border-gray-800 bg-[#0f172a] p-5">
      <div className={`text-3xl font-bold font-mono ${color}`}>{value}</div>
      <div className="mt-1 text-xs uppercase text-gray-500 tracking-wider">{label}</div>
    </div>
  );
}
