import { Link } from "react-router-dom";

const GICS_NAMES: Record<string, string> = {
  "10": "Energy",
  "15": "Materials",
  "20": "Industrials",
  "25": "Consumer Disc.",
  "30": "Consumer Staples",
  "35": "Health Care",
  "40": "Financials",
  "45": "Info Tech",
  "50": "Comm. Services",
  "55": "Utilities",
  "60": "Real Estate",
};

function classificationBadge(classification: string) {
  const colors: Record<string, string> = {
    Buy: "bg-green-900/50 text-green-400 border-green-800",
    Hold: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
    Sell: "bg-red-900/50 text-red-400 border-red-800",
  };
  return colors[classification] || "bg-gray-800 text-gray-400 border-gray-700";
}

function scoreColor(score: number): string {
  if (score >= 60) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

export interface RecommendationRow {
  ticker: string;
  name: string;
  country_iso2: string;
  gics_code: string;
  company_score: number;
  country_score: number;
  industry_score: number;
  composite_score: number;
  classification: string;
  rank: number;
  rank_total: number;
  as_of: string;
  recommendation_version: string;
}

export default function RecommendationTable({
  recommendations,
}: {
  recommendations: RecommendationRow[];
}) {
  if (recommendations.length === 0) {
    return (
      <div className="p-8 text-center">
        <p className="text-gray-500">No recommendations yet.</p>
        <p className="mt-1 text-sm text-gray-600">
          Run country, industry, and company refresh jobs first.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
            <th className="px-4 py-3 w-16">Rank</th>
            <th className="px-4 py-3">Company</th>
            <th className="px-4 py-3">Country</th>
            <th className="px-4 py-3">Sector</th>
            <th className="px-4 py-3 text-right">Composite</th>
            <th className="px-4 py-3 text-right">Company</th>
            <th className="px-4 py-3 text-right">Country</th>
            <th className="px-4 py-3 text-right">Industry</th>
            <th className="px-4 py-3 text-center">Signal</th>
          </tr>
        </thead>
        <tbody>
          {recommendations.map((row) => (
            <tr
              key={row.ticker}
              className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
            >
              <td className="px-4 py-3 text-gray-500">{row.rank}</td>
              <td className="px-4 py-3">
                <Link
                  to={`/companies/${row.ticker}`}
                  className="text-white hover:text-brand transition-colors"
                >
                  {row.name}
                </Link>
                <span className="ml-2 text-xs text-gray-600">
                  {row.ticker}
                </span>
              </td>
              <td className="px-4 py-3 text-gray-400">{row.country_iso2}</td>
              <td className="px-4 py-3 text-gray-400">
                {GICS_NAMES[row.gics_code] || row.gics_code}
              </td>
              <td
                className={`px-4 py-3 text-right font-mono text-base font-bold ${scoreColor(row.composite_score)}`}
              >
                {row.composite_score.toFixed(1)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-gray-400">
                {row.company_score.toFixed(1)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-gray-400">
                {row.country_score.toFixed(1)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-gray-400">
                {row.industry_score.toFixed(1)}
              </td>
              <td className="px-4 py-3 text-center">
                <span
                  className={`inline-block rounded-full border px-3 py-0.5 text-xs font-bold ${classificationBadge(row.classification)}`}
                >
                  {row.classification}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
