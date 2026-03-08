import { Link } from "react-router-dom";

function scoreColor(score: number): string {
  if (score >= 60) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function rankBadge(rank: number, total: number): string {
  const pct = rank / total;
  if (pct <= 0.3) return "text-green-400 bg-green-950/50";
  if (pct <= 0.7) return "text-yellow-400 bg-yellow-950/50";
  return "text-red-400 bg-red-950/50";
}

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

export interface CompanyRow {
  ticker: string;
  name: string;
  gics_code: string;
  country_iso2: string;
  overall_score: number;
  fundamental_score: number;
  market_score: number;
  industry_context_score: number;
  rank: number;
  rank_total?: number;
  as_of: string;
  calc_version: string;
}

export default function CompanyTable({
  companies,
}: {
  companies: CompanyRow[];
}) {
  if (companies.length === 0) {
    return (
      <div className="p-8 text-center">
        <p className="text-gray-500">No company scores yet.</p>
        <p className="mt-1 text-sm text-gray-600">
          Run a company refresh job to compute scores.
        </p>
      </div>
    );
  }

  const total = companies.length;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
            <th className="px-4 py-3 w-16">Rank</th>
            <th className="px-4 py-3">Company</th>
            <th className="px-4 py-3">Country</th>
            <th className="px-4 py-3">Sector</th>
            <th className="px-4 py-3 text-right">Overall</th>
            <th className="px-4 py-3 text-right">Fundamental</th>
            <th className="px-4 py-3 text-right">Market</th>
          </tr>
        </thead>
        <tbody>
          {companies.map((row) => (
            <tr
              key={row.ticker}
              className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
            >
              <td className="px-4 py-3">
                <span
                  className={`inline-flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${rankBadge(row.rank, total)}`}
                >
                  {row.rank}
                </span>
              </td>
              <td className="px-4 py-3">
                <Link
                  to={`/stocks/${row.ticker}`}
                  className="text-white hover:text-brand transition-colors"
                >
                  {row.name}
                </Link>
                <span className="ml-2 text-xs text-gray-600">
                  {row.ticker}
                </span>
              </td>
              <td className="px-4 py-3 text-gray-400">
                {row.country_iso2}
              </td>
              <td className="px-4 py-3 text-gray-400">
                {GICS_NAMES[row.gics_code] || row.gics_code}
              </td>
              <td
                className={`px-4 py-3 text-right font-mono text-base font-bold ${scoreColor(row.overall_score)}`}
              >
                {row.overall_score.toFixed(1)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-gray-400">
                {row.fundamental_score.toFixed(1)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-gray-400">
                {row.market_score.toFixed(1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
