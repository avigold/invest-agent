"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import CountryTable, { CountryRow } from "@/components/CountryTable";

export default function CountriesPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [countries, setCountries] = useState<CountryRow[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  const loadCountries = () => {
    apiJson<CountryRow[]>("/v1/countries")
      .then(setCountries)
      .catch(() => {});
  };

  useEffect(() => {
    if (user) loadCountries();
  }, [user]);

  const submitRefresh = async () => {
    setSubmitting(true);
    setError("");
    try {
      const result = await apiJson<{ id: string }>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "country_refresh",
          params: {},
        }),
      });
      router.push(`/jobs/${result.id}`);
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
        <h1 className="text-2xl font-bold text-white">Countries</h1>
        <button
          onClick={submitRefresh}
          disabled={submitting}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {submitting ? "Submitting..." : "Refresh Countries"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="rounded-lg border border-gray-800 bg-gray-900">
        <CountryTable countries={countries} />
      </div>
    </div>
  );
}
