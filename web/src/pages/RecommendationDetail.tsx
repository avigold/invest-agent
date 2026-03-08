import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { useRecommendationDetail, queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";

interface ScoreEntry {
  score: number;
  weight: number;
}

interface CountryInfo {
  iso2: string;
  name: string;
  overall_score: number;
}

interface IndustryInfo {
  gics_code: string;
  name: string;
  country_iso2: string;
  overall_score: number;
}

interface CompanyInfo {
  ticker: string;
  name: string;
  overall_score: number;
}

interface Analysis {
  summary: string;
  country_assessment: string;
  industry_assessment: string;
  company_assessment: string;
  risks_and_catalysts: string;
  model_id: string;
  analysis_version: string;
  created_at: string | null;
}

interface RecommendationDetailData {
  ticker: string;
  name: string;
  classification: string;
  composite_score: number;
  rank: number;
  rank_total: number;
  as_of: string;
  recommendation_version: string;
  scores: {
    company: ScoreEntry;
    country: ScoreEntry;
    industry: ScoreEntry;
  };
  country: CountryInfo;
  industry: IndustryInfo;
  company: CompanyInfo;
  analysis: Analysis | null;
}

interface JobResponse {
  id: string;
  command: string;
  status: string;
}

function classificationBadge(classification: string) {
  const colors: Record<string, string> = {
    Buy: "bg-green-900/50 text-green-400 border-green-800",
    Hold: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
    Sell: "bg-red-900/50 text-red-400 border-red-800",
  };
  return colors[classification] || "bg-gray-800 text-gray-400 border-gray-700";
}

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function barColor(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 40) return "bg-yellow-500";
  return "bg-red-500";
}

function rankColor(rank: number, total: number): string {
  const pct = rank / total;
  if (pct <= 0.3) return "text-green-400";
  if (pct <= 0.7) return "text-yellow-400";
  return "text-red-400";
}

function rankLabel(rank: number, total: number): string {
  if (rank === 1) return "Top ranked";
  if (rank <= Math.ceil(total * 0.3)) return "Upper tier";
  if (rank <= Math.ceil(total * 0.7)) return "Mid tier";
  return "Lower tier";
}

const ANALYSIS_SECTIONS: { key: keyof Analysis; label: string }[] = [
  { key: "summary", label: "Summary" },
  { key: "country_assessment", label: "Country Assessment" },
  { key: "industry_assessment", label: "Industry Assessment" },
  { key: "company_assessment", label: "Company Assessment" },
  { key: "risks_and_catalysts", label: "Risks & Catalysts" },
];

export default function RecommendationDetail() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { ticker: rawTicker } = useParams<{ ticker: string }>();
  const ticker = rawTicker?.toUpperCase() || "";
  const { data, error: queryError } = useRecommendationDetail<RecommendationDetailData>(ticker);
  const error = queryError ? (queryError instanceof Error ? queryError.message : "Failed to load") : "";
  const [jobStatus, setJobStatus] = useState<"idle" | "running" | "done" | "failed">("idle");
  const [jobError, setJobError] = useState("");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  const generateAnalysis = async () => {
    setJobStatus("running");
    setJobError("");
    try {
      const job = await apiJson<JobResponse>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "recommendation_analysis",
          params: { ticker },
        }),
      });

      // Poll job status until done
      const pollInterval = setInterval(async () => {
        try {
          const status = await apiJson<JobResponse>(`/api/jobs/${job.id}`);
          if (status.status === "done") {
            clearInterval(pollInterval);
            setJobStatus("done");
            queryClient.invalidateQueries({ queryKey: queryKeys.recommendation(ticker) });
          } else if (status.status === "failed" || status.status === "cancelled") {
            clearInterval(pollInterval);
            setJobStatus("failed");
            setJobError("Analysis generation failed. Check job logs for details.");
          }
        } catch {
          clearInterval(pollInterval);
          setJobStatus("failed");
          setJobError("Failed to check job status.");
        }
      }, 2000);
    } catch (e) {
      setJobStatus("failed");
      setJobError(e instanceof Error ? e.message : "Failed to start analysis job");
    }
  };

  if (loading || !user) return null;

  if (error) {
    return (
      <div>
        <Link to="/fundamentals" className="mb-4 inline-block text-sm text-brand hover:underline">
          &larr; Back to Recommendations
        </Link>
        <div className="rounded border border-red-800 bg-red-900/30 px-4 py-3 text-red-300">
          {error}
        </div>
      </div>
    );
  }

  if (!data) {
    return <div className="text-gray-400">Loading...</div>;
  }

  const { scores, country, industry, company, analysis } = data;

  return (
    <div>
      <Link to="/fundamentals" className="mb-6 inline-block text-sm text-gray-400 hover:text-white">
        &larr; All recommendations
      </Link>

      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold text-white">{data.name}</h1>
          <span className="rounded bg-gray-800 px-2 py-1 text-sm text-gray-400">{data.ticker}</span>
          <span className={`inline-block rounded-full border px-3 py-0.5 text-sm font-bold ${classificationBadge(data.classification)}`}>
            {data.classification}
          </span>
        </div>
        <div className="mt-2 flex items-center gap-4">
          <span className={`text-lg font-semibold ${rankColor(data.rank, data.rank_total)}`}>
            #{data.rank} of {data.rank_total}
          </span>
          <span className="text-sm text-gray-500">
            {rankLabel(data.rank, data.rank_total)}
          </span>
          <span className="text-sm text-gray-600">
            as of {data.as_of}
          </span>
        </div>
      </div>

      {/* Composite Score */}
      <div className="mb-8 rounded-lg border border-gray-800 bg-gray-900 p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <div className="text-xs font-medium uppercase text-gray-400">Composite Score</div>
            <div className={`text-4xl font-bold ${scoreColor(data.composite_score)}`}>
              {data.composite_score.toFixed(1)}
            </div>
          </div>
        </div>

        {/* Weighted breakdown bar */}
        <div className="mb-2 flex h-3 w-full overflow-hidden rounded-full bg-gray-800">
          <div
            className="bg-blue-500"
            style={{ width: `${scores.country.weight * 100}%`, opacity: 0.6 + (scores.country.score / 100) * 0.4 }}
            title={`Country: ${scores.country.score.toFixed(1)} (${scores.country.weight * 100}%)`}
          />
          <div
            className="bg-purple-500"
            style={{ width: `${scores.industry.weight * 100}%`, opacity: 0.6 + (scores.industry.score / 100) * 0.4 }}
            title={`Industry: ${scores.industry.score.toFixed(1)} (${scores.industry.weight * 100}%)`}
          />
          <div
            className="bg-emerald-500"
            style={{ width: `${scores.company.weight * 100}%`, opacity: 0.6 + (scores.company.score / 100) * 0.4 }}
            title={`Company: ${scores.company.score.toFixed(1)} (${scores.company.weight * 100}%)`}
          />
        </div>
        <div className="flex text-xs text-gray-500">
          <div style={{ width: `${scores.country.weight * 100}%` }}>Country {scores.country.weight * 100}%</div>
          <div style={{ width: `${scores.industry.weight * 100}%` }}>Industry {scores.industry.weight * 100}%</div>
          <div style={{ width: `${scores.company.weight * 100}%` }}>Company {scores.company.weight * 100}%</div>
        </div>
      </div>

      {/* Three score cards with links */}
      <div className="mb-8 grid gap-4 md:grid-cols-3">
        {/* Country */}
        <Link
          to={`/countries/${country.iso2}`}
          className="group rounded-lg border border-gray-800 bg-gray-900 p-4 hover:border-blue-700 transition-colors"
        >
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-medium uppercase text-gray-400">Country (20%)</span>
            <span className="text-xs text-gray-600 group-hover:text-brand transition-colors">View details &rarr;</span>
          </div>
          <div className="text-sm text-gray-300 mb-1">{country.name}</div>
          <div className={`text-2xl font-bold ${scoreColor(country.overall_score)}`}>
            {country.overall_score.toFixed(1)}
          </div>
          <div className="mt-2 h-1.5 w-full rounded-full bg-gray-700">
            <div className={`h-1.5 rounded-full ${barColor(country.overall_score)}`} style={{ width: `${country.overall_score}%` }} />
          </div>
        </Link>

        {/* Industry */}
        <Link
          to={`/industries/${industry.gics_code}?iso2=${industry.country_iso2}`}
          className="group rounded-lg border border-gray-800 bg-gray-900 p-4 hover:border-purple-700 transition-colors"
        >
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-medium uppercase text-gray-400">Industry (20%)</span>
            <span className="text-xs text-gray-600 group-hover:text-brand transition-colors">View details &rarr;</span>
          </div>
          <div className="text-sm text-gray-300 mb-1">{industry.name}</div>
          <div className={`text-2xl font-bold ${scoreColor(industry.overall_score)}`}>
            {industry.overall_score.toFixed(1)}
          </div>
          <div className="mt-2 h-1.5 w-full rounded-full bg-gray-700">
            <div className={`h-1.5 rounded-full ${barColor(industry.overall_score)}`} style={{ width: `${industry.overall_score}%` }} />
          </div>
        </Link>

        {/* Company */}
        <Link
          to={`/companies/${company.ticker}`}
          className="group rounded-lg border border-gray-800 bg-gray-900 p-4 hover:border-emerald-700 transition-colors"
        >
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-medium uppercase text-gray-400">Company (60%)</span>
            <span className="text-xs text-gray-600 group-hover:text-brand transition-colors">View details &rarr;</span>
          </div>
          <div className="text-sm text-gray-300 mb-1">{company.name}</div>
          <div className={`text-2xl font-bold ${scoreColor(company.overall_score)}`}>
            {company.overall_score.toFixed(1)}
          </div>
          <div className="mt-2 h-1.5 w-full rounded-full bg-gray-700">
            <div className={`h-1.5 rounded-full ${barColor(company.overall_score)}`} style={{ width: `${company.overall_score}%` }} />
          </div>
        </Link>
      </div>

      {/* AI Analysis */}
      <div className="mb-8">
        <h2 className="mb-4 text-lg font-semibold text-white">Analysis</h2>
        {analysis ? (
          <div className="space-y-4">
            {ANALYSIS_SECTIONS.map(({ key, label }) => {
              const text = analysis[key];
              if (!text || typeof text !== "string") return null;
              return (
                <div key={key} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                  <h3 className="mb-2 text-sm font-semibold uppercase text-gray-400">{label}</h3>
                  <p className="text-sm leading-relaxed text-gray-300 whitespace-pre-line">{text}</p>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-6 text-center">
            {jobStatus === "running" ? (
              <div className="flex items-center justify-center gap-3 text-gray-400">
                <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Generating analysis...
              </div>
            ) : (
              <div>
                <p className="mb-3 text-gray-500">
                  No analysis available yet for this recommendation.
                </p>
                {jobError && (
                  <p className="mb-3 text-sm text-red-400">{jobError}</p>
                )}
                <button
                  onClick={generateAnalysis}
                  disabled={jobStatus !== "idle" && jobStatus !== "done" && jobStatus !== "failed"}
                  className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand/80 disabled:opacity-50 transition-colors"
                >
                  Generate Analysis
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Metadata */}
      <div className="mt-6 rounded-lg border border-gray-800/50 bg-gray-950 px-4 py-3 text-xs text-gray-600">
        {data.recommendation_version}
        {analysis && (
          <>
            {" "}&middot; model: {analysis.model_id}
            {" "}&middot; {analysis.analysis_version}
            {analysis.created_at && (
              <> &middot; generated {new Date(analysis.created_at).toLocaleDateString()}</>
            )}
          </>
        )}
      </div>
    </div>
  );
}
