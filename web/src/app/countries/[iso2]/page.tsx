"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import ScoreCard from "@/components/ScoreCard";

interface CountryPacket {
  iso2: string;
  country_name: string;
  as_of: string;
  calc_version: string;
  summary_version: string;
  scores: {
    overall: number;
    macro: number;
    market: number;
    stability: number;
  };
  rank: number;
  rank_total: number;
  component_data: {
    macro_indicators?: Record<string, number | null>;
    market_metrics?: Record<string, number | null>;
    stability_value?: number | null;
  };
  risks: Array<{
    type: string;
    severity: string;
    description: string;
  }>;
  evidence: Array<{
    series: string;
    value: number;
    date: string;
    artefact_id: string;
    source: string;
    source_url: string;
  }> | null;
}

const MACRO_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  gdp: { label: "GDP", format: (v) => `$${(v / 1e12).toFixed(2)}T` },
  gdp_growth: { label: "GDP Growth", format: (v) => `${v.toFixed(2)}%` },
  inflation: { label: "Inflation", format: (v) => `${v.toFixed(2)}%` },
  unemployment: { label: "Unemployment", format: (v) => `${v.toFixed(2)}%` },
  govt_debt_gdp: { label: "Govt Debt / GDP", format: (v) => `${v.toFixed(1)}%` },
  current_account_gdp: { label: "Current Account / GDP", format: (v) => `${v.toFixed(2)}%` },
  fdi_gdp: { label: "FDI / GDP", format: (v) => `${v.toFixed(2)}%` },
  reserves: { label: "Foreign Reserves", format: (v) => `$${(v / 1e9).toFixed(1)}B` },
};

const MARKET_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  return_1y: { label: "1-Year Return", format: (v) => `${(v * 100).toFixed(1)}%` },
  max_drawdown: { label: "Max Drawdown (12mo)", format: (v) => `${(v * 100).toFixed(1)}%` },
  ma_spread: { label: "Price vs 200-Day MA", format: (v) => `${(v * 100).toFixed(1)}%` },
};

function severityColor(severity: string): string {
  if (severity === "high") return "border-red-700 bg-red-950/50 text-red-300";
  if (severity === "medium") return "border-yellow-700 bg-yellow-950/50 text-yellow-300";
  return "border-gray-700 bg-gray-800 text-gray-300";
}

function severityDot(severity: string): string {
  if (severity === "high") return "bg-red-400";
  if (severity === "medium") return "bg-yellow-400";
  return "bg-gray-400";
}

function rankLabel(rank: number, total: number): string {
  if (rank === 1) return "Top ranked";
  if (rank <= Math.ceil(total * 0.3)) return "Upper tier";
  if (rank <= Math.ceil(total * 0.7)) return "Mid tier";
  return "Lower tier";
}

function rankColor(rank: number, total: number): string {
  const pct = rank / total;
  if (pct <= 0.3) return "text-green-400";
  if (pct <= 0.7) return "text-yellow-400";
  return "text-red-400";
}

export default function CountryDetailPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const params = useParams();
  const iso2 = (params.iso2 as string)?.toUpperCase();
  const [packet, setPacket] = useState<CountryPacket | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  useEffect(() => {
    if (user && iso2) {
      apiJson<CountryPacket>(
        `/v1/country/${iso2}/summary?include_evidence=true`
      )
        .then(setPacket)
        .catch((e) => setError(e.message));
    }
  }, [user, iso2]);

  if (loading || !user) return null;

  if (error) {
    return (
      <div>
        <Link href="/countries" className="mb-4 inline-block text-sm text-brand hover:underline">
          &larr; Back to Countries
        </Link>
        <div className="rounded border border-red-800 bg-red-900/30 px-4 py-3 text-red-300">
          {error}
        </div>
      </div>
    );
  }

  if (!packet) {
    return <div className="text-gray-400">Loading...</div>;
  }

  const { scores, component_data, risks, evidence } = packet;
  const macroIndicators = component_data?.macro_indicators || {};
  const marketMetrics = component_data?.market_metrics || {};

  return (
    <div>
      <Link href="/countries" className="mb-6 inline-block text-sm text-gray-400 hover:text-white">
        &larr; All countries
      </Link>

      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold text-white">{packet.country_name}</h1>
          <span className="rounded bg-gray-800 px-2 py-1 text-sm text-gray-400">{packet.iso2}</span>
        </div>
        <div className="mt-2 flex items-center gap-4">
          <span className={`text-lg font-semibold ${rankColor(packet.rank, packet.rank_total)}`}>
            #{packet.rank} of {packet.rank_total}
          </span>
          <span className="text-sm text-gray-500">
            {rankLabel(packet.rank, packet.rank_total)}
          </span>
          <span className="text-sm text-gray-600">
            as of {packet.as_of}
          </span>
        </div>
      </div>

      {/* Score cards */}
      <div className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-4">
        <ScoreCard label="Overall" score={scores.overall} />
        <ScoreCard label="Macro (45%)" score={scores.macro} />
        <ScoreCard label="Market (35%)" score={scores.market} />
        <ScoreCard label="Stability (20%)" score={scores.stability} />
      </div>

      {/* Risks */}
      {risks.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white">Risks</h2>
          <div className="space-y-2">
            {risks.map((r, i) => (
              <div key={i} className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${severityColor(r.severity)}`}>
                <span className={`mt-1.5 h-2 w-2 flex-shrink-0 rounded-full ${severityDot(r.severity)}`} />
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wide">
                    {r.severity}
                  </span>
                  <p className="mt-0.5 text-sm">{r.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Two-column layout for indicators */}
      <div className="mb-8 grid gap-6 md:grid-cols-2">
        {/* Macro indicators */}
        <div>
          <h2 className="mb-3 text-lg font-semibold text-white">Macro Indicators</h2>
          <div className="rounded-lg border border-gray-800 bg-gray-900">
            <div className="divide-y divide-gray-800/50">
              {Object.entries(macroIndicators).map(([key, val]) => {
                const meta = MACRO_LABELS[key];
                return (
                  <div key={key} className="flex items-center justify-between px-4 py-2.5">
                    <span className="text-sm text-gray-400">
                      {meta?.label || key.replace(/_/g, " ")}
                    </span>
                    <span className="font-mono text-sm font-medium text-white">
                      {val != null && meta ? meta.format(val) : val != null ? String(val) : "—"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Market metrics */}
        <div>
          <h2 className="mb-3 text-lg font-semibold text-white">Market Metrics</h2>
          <div className="rounded-lg border border-gray-800 bg-gray-900">
            <div className="divide-y divide-gray-800/50">
              {Object.entries(marketMetrics).map(([key, val]) => {
                const meta = MARKET_LABELS[key];
                const isNeg = val != null && val < 0;
                return (
                  <div key={key} className="flex items-center justify-between px-4 py-2.5">
                    <span className="text-sm text-gray-400">
                      {meta?.label || key.replace(/_/g, " ")}
                    </span>
                    <span className={`font-mono text-sm font-medium ${isNeg ? "text-red-400" : "text-white"}`}>
                      {val != null && meta ? meta.format(val) : val != null ? String(val) : "—"}
                    </span>
                  </div>
                );
              })}
              {component_data.stability_value != null && (
                <div className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-sm text-gray-400">Stability Index</span>
                  <span className="font-mono text-sm font-medium text-white">
                    {(component_data.stability_value * 100).toFixed(0)} / 100
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Evidence */}
      {evidence && evidence.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-white">
            Evidence Chain
            <span className="ml-2 text-sm font-normal text-gray-500">
              {evidence.length} data points
            </span>
          </h2>
          <div className="overflow-x-auto rounded-lg border border-gray-800 bg-gray-900">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-4 py-3">Series</th>
                  <th className="px-4 py-3 text-right">Value</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3 text-xs font-normal normal-case text-gray-600">Artefact</th>
                </tr>
              </thead>
              <tbody>
                {evidence.map((e, i) => (
                  <tr key={i} className="border-b border-gray-800/50">
                    <td className="px-4 py-2 text-gray-300">
                      {e.series.replace(/_/g, " ")}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-white">
                      {formatEvidence(e.series, e.value)}
                    </td>
                    <td className="px-4 py-2 text-gray-400">{e.date}</td>
                    <td className="px-4 py-2 text-gray-500">{e.source}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-600">
                      {e.artefact_id.substring(0, 8)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Metadata */}
      <div className="mt-6 rounded-lg border border-gray-800/50 bg-gray-950 px-4 py-3 text-xs text-gray-600">
        calc_version: {packet.calc_version} &middot; summary_version: {packet.summary_version}
      </div>
    </div>
  );
}

function formatEvidence(series: string, value: number): string {
  if (series === "gdp" || series === "reserves") {
    if (Math.abs(value) >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
    if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
    return `$${value.toFixed(0)}`;
  }
  if (series === "equity_close") return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (series.includes("gdp") || series.includes("inflation") || series.includes("unemployment")) {
    return `${value.toFixed(2)}%`;
  }
  if (series.startsWith("fred_")) return value.toFixed(2);
  if (series === "stability") return `${(value * 100).toFixed(0)}`;
  return value.toFixed(4);
}
