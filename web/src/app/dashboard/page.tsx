"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import JobsTable, { JobRow } from "@/components/JobsTable";

interface CountryPreview {
  iso2: string;
  name: string;
  overall_score: number;
  rank: number;
}

export default function DashboardPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [recentJobs, setRecentJobs] = useState<JobRow[]>([]);
  const [topCountries, setTopCountries] = useState<CountryPreview[]>([]);

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
      apiJson<CountryPreview[]>("/v1/countries")
        .then((c) => setTopCountries(c.slice(0, 3)))
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

      {topCountries.length > 0 && (
        <div className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Top Countries</h2>
            <Link href="/countries" className="text-sm text-brand hover:underline">
              View all
            </Link>
          </div>
          <div className="grid grid-cols-3 gap-4">
            {topCountries.map((c) => (
              <Link
                key={c.iso2}
                href={`/countries/${c.iso2}`}
                className="rounded-lg border border-gray-800 bg-gray-900 p-4 hover:border-gray-700"
              >
                <div className="text-xs text-gray-500">#{c.rank}</div>
                <div className="text-lg font-bold text-white">{c.name}</div>
                <div className="text-2xl font-bold text-green-400">
                  {c.overall_score.toFixed(1)}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

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
