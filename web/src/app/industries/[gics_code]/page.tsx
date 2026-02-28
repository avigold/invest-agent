"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import ScoreCard from "@/components/ScoreCard";

interface Signal {
  indicator: string;
  value: number | null;
  threshold: number;
  favorable_when: string;
  signal: number;
  reason?: string;
}

interface Risk {
  type: string;
  severity: string;
  description: string;
}

interface IndustrySummary {
  gics_code: string;
  industry_name: string;
  country_iso2: string;
  country_name: string;
  as_of: string;
  calc_version: string;
  summary_version: string;
  scores: {
    overall: number;
    rubric: number;
  };
  rank: number;
  rank_total: number;
  component_data: {
    raw_score: number;
    max_possible: number;
    min_possible: number;
    signals: Signal[];
    country_macro_summary?: Record<string, number>;
  };
  risks: Risk[];
}

function signalIcon(signal: number): string {
  if (signal === 1) return "+";
  if (signal === -1) return "-";
  return "?";
}

function signalColor(signal: number): string {
  if (signal === 1) return "text-green-400";
  if (signal === -1) return "text-red-400";
  return "text-gray-500";
}

function severityColor(severity: string): string {
  if (severity === "high") return "text-red-400 bg-red-950/50";
  if (severity === "medium") return "text-yellow-400 bg-yellow-950/50";
  return "text-gray-400 bg-gray-800";
}

function formatIndicator(name: string): string {
  return name
    .replace(/_pct$/, "")
    .replace(/_bps$/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(indicator: string, value: number | null): string {
  if (value === null) return "N/A";
  if (indicator.endsWith("_bps")) return `${value.toFixed(0)} bps`;
  if (indicator === "stability_index") return value.toFixed(3);
  return `${value.toFixed(1)}%`;
}

export default function IndustryDetailPage({
  params,
}: {
  params: { gics_code: string };
}) {
  const { user, loading } = useUser();
  const router = useRouter();
  const searchParams = useSearchParams();
  const iso2 = searchParams.get("iso2") || "US";
  const [summary, setSummary] = useState<IndustrySummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  useEffect(() => {
    if (user) {
      apiJson<IndustrySummary>(
        `/v1/industry/${params.gics_code}/summary?iso2=${iso2}`
      )
        .then(setSummary)
        .catch((e) =>
          setError(e instanceof Error ? e.message : "Failed to load")
        );
    }
  }, [user, params.gics_code, iso2]);

  if (loading || !user) return null;

  if (error) {
    return (
      <div className="rounded border border-red-800 bg-red-900/30 px-4 py-3 text-red-300">
        {error}
      </div>
    );
  }

  if (!summary) {
    return <p className="text-gray-500">Loading...</p>;
  }

  const { scores, component_data, risks } = summary;
  const tierPct = summary.rank / summary.rank_total;
  const tierLabel =
    tierPct <= 0.3 ? "Top Tier" : tierPct <= 0.7 ? "Mid Tier" : "Bottom Tier";
  const tierColor =
    tierPct <= 0.3
      ? "text-green-400"
      : tierPct <= 0.7
        ? "text-yellow-400"
        : "text-red-400";

  return (
    <div>
      {/* Back link */}
      <Link
        href="/industries"
        className="mb-4 inline-block text-sm text-gray-400 hover:text-white"
      >
        &larr; All Industries
      </Link>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">
            {summary.industry_name}
            <span className="ml-3 text-base text-gray-500">
              GICS {summary.gics_code}
            </span>
          </h1>
          <p className="mt-1 text-gray-400">
            <Link
              href={`/countries/${summary.country_iso2}`}
              className="hover:text-white transition-colors"
            >
              {summary.country_name}
            </Link>
            <span className="mx-2 text-gray-600">|</span>
            <span className={tierColor}>
              #{summary.rank}/{summary.rank_total} {tierLabel}
            </span>
            <span className="mx-2 text-gray-600">|</span>
            <span className="text-sm text-gray-500">
              as of {summary.as_of}
            </span>
          </p>
        </div>
      </div>

      {/* Score cards */}
      <div className="mb-6 grid grid-cols-2 gap-4">
        <ScoreCard label="Overall Score" score={scores.overall} />
        <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
          <p className="text-xs uppercase text-gray-500">Rubric Score</p>
          <p className="mt-1 text-2xl font-bold font-mono text-white">
            {scores.rubric > 0 ? "+" : ""}
            {scores.rubric}
            <span className="ml-2 text-sm text-gray-500">
              / {component_data.max_possible}
            </span>
          </p>
          <div className="mt-2 h-1.5 rounded-full bg-gray-800">
            <div
              className="h-1.5 rounded-full bg-brand"
              style={{
                width: `${((scores.rubric - component_data.min_possible) / (component_data.max_possible - component_data.min_possible)) * 100}%`,
              }}
            />
          </div>
        </div>
      </div>

      {/* Risks */}
      {risks.length > 0 && (
        <div className="mb-6 rounded-lg border border-gray-800 bg-gray-900 p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase text-gray-500">
            Risk Flags
          </h2>
          <div className="space-y-2">
            {risks.map((r, i) => (
              <div key={i} className="flex items-center gap-3">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium ${severityColor(r.severity)}`}
                >
                  {r.severity}
                </span>
                <span className="text-sm text-gray-300">{r.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Macro Sensitivity Signals */}
      <div className="mb-6 rounded-lg border border-gray-800 bg-gray-900 p-4">
        <h2 className="mb-3 text-sm font-semibold uppercase text-gray-500">
          Macro Sensitivity Signals
        </h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
              <th className="px-4 py-2">Indicator</th>
              <th className="px-4 py-2 text-right">Value</th>
              <th className="px-4 py-2 text-right">Threshold</th>
              <th className="px-4 py-2 text-center">Favorable When</th>
              <th className="px-4 py-2 text-center">Signal</th>
            </tr>
          </thead>
          <tbody>
            {component_data.signals.map((s) => (
              <tr
                key={s.indicator}
                className="border-b border-gray-800/50"
              >
                <td className="px-4 py-2 text-gray-300">
                  {formatIndicator(s.indicator)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-gray-300">
                  {formatValue(s.indicator, s.value)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-gray-500">
                  {formatValue(s.indicator, s.threshold)}
                </td>
                <td className="px-4 py-2 text-center text-gray-500">
                  {s.favorable_when}
                </td>
                <td className="px-4 py-2 text-center">
                  <span
                    className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-sm font-bold ${signalColor(s.signal)}`}
                  >
                    {signalIcon(s.signal)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Country Macro Summary */}
      {component_data.country_macro_summary &&
        Object.keys(component_data.country_macro_summary).length > 0 && (
          <div className="mb-6 rounded-lg border border-gray-800 bg-gray-900 p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase text-gray-500">
              Country Macro Context
            </h2>
            <div className="grid grid-cols-2 gap-x-8 gap-y-2 sm:grid-cols-3">
              {Object.entries(component_data.country_macro_summary).map(
                ([key, val]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-sm text-gray-500">
                      {key.replace(/_/g, " ")}
                    </span>
                    <span className="font-mono text-sm text-gray-300">
                      {typeof val === "number" ? val.toFixed(2) : String(val)}
                    </span>
                  </div>
                )
              )}
            </div>
          </div>
        )}

      {/* Metadata */}
      <div className="text-xs text-gray-600">
        calc_version: {summary.calc_version} | summary_version:{" "}
        {summary.summary_version}
      </div>
    </div>
  );
}
