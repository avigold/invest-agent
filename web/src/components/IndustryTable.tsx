import Link from "next/link";

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

export interface IndustryRow {
  gics_code: string;
  industry_name: string;
  country_iso2: string;
  country_name: string;
  overall_score: number;
  rubric_score: number;
  rank: number;
  as_of: string;
  calc_version: string;
}

export default function IndustryTable({
  industries,
  showCountry = true,
}: {
  industries: IndustryRow[];
  showCountry?: boolean;
}) {
  if (industries.length === 0) {
    return (
      <div className="p-8 text-center">
        <p className="text-gray-500">No industry scores yet.</p>
        <p className="mt-1 text-sm text-gray-600">
          Run an industry refresh job to compute sector scores.
        </p>
      </div>
    );
  }

  const total = industries.length;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
            <th className="px-4 py-3 w-16">Rank</th>
            <th className="px-4 py-3">Sector</th>
            {showCountry && <th className="px-4 py-3">Country</th>}
            <th className="px-4 py-3 text-right">Score</th>
            <th className="px-4 py-3 text-right">Rubric</th>
          </tr>
        </thead>
        <tbody>
          {industries.map((row) => (
            <tr
              key={`${row.gics_code}-${row.country_iso2}`}
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
                  href={`/industries/${row.gics_code}?iso2=${row.country_iso2}`}
                  className="text-white hover:text-brand transition-colors"
                >
                  {row.industry_name}
                </Link>
                <span className="ml-2 text-xs text-gray-600">
                  {row.gics_code}
                </span>
              </td>
              {showCountry && (
                <td className="px-4 py-3">
                  <Link
                    href={`/countries/${row.country_iso2}`}
                    className="text-gray-400 hover:text-white transition-colors"
                  >
                    {row.country_name}
                  </Link>
                  <span className="ml-1 text-xs text-gray-600">
                    {row.country_iso2}
                  </span>
                </td>
              )}
              <td
                className={`px-4 py-3 text-right font-mono text-base font-bold ${scoreColor(row.overall_score)}`}
              >
                {row.overall_score.toFixed(1)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-gray-400">
                {row.rubric_score > 0 ? "+" : ""}
                {row.rubric_score}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
