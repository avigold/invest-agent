"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import JobsTable, { JobRow } from "@/components/JobsTable";

export default function DashboardPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [recentJobs, setRecentJobs] = useState<JobRow[]>([]);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [user, loading, router]);

  useEffect(() => {
    if (user) {
      apiJson<JobRow[]>("/api/jobs")
        .then((jobs) => setRecentJobs(jobs.slice(0, 5)))
        .catch(() => {});
    }
  }, [user]);

  if (loading || !user) return null;

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">
          Welcome, {user.name}
        </h1>
        <p className="text-gray-400">
          Plan: <span className="uppercase">{user.plan}</span>
        </p>
      </div>

      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Recent jobs</h2>
        <Link
          href="/jobs"
          className="text-sm text-brand hover:underline"
        >
          View all
        </Link>
      </div>
      <div className="rounded-lg border border-gray-800 bg-gray-900">
        <JobsTable jobs={recentJobs} />
      </div>
    </div>
  );
}
