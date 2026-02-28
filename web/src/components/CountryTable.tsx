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

export interface CountryRow {
  iso2: string;
  name: string;
  overall_score: number;
  macro_score: number;
  market_score: number;
  stability_score: number;
  rank: number;
  as_of: string;
  calc_version: string;
}

export default function CountryTable({
  countries,
}: {
  countries: CountryRow[];
}) {
  if (countries.length === 0) {
    return (
      <div className="p-8 text-center">
        <p className="text-gray-500">No country scores yet.</p>
        <p className="mt-1 text-sm text-gray-600">
          Run a country refresh job to ingest data and compute scores.
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
            <th className="px-4 py-3">Country</th>
            <th className="px-4 py-3 text-right">Overall</th>
            <th className="px-4 py-3 text-right">Macro</th>
            <th className="px-4 py-3 text-right">Market</th>
            <th className="px-4 py-3 text-right">Stability</th>
          </tr>
        </thead>
        <tbody>
          {countries.map((c) => (
            <tr
              key={c.iso2}
              className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
            >
              <td className="px-4 py-3">
                <span className={`inline-flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${rankBadge(c.rank, countries.length)}`}>
                  {c.rank}
                </span>
              </td>
              <td className="px-4 py-3">
                <Link
                  href={`/countries/${c.iso2}`}
                  className="text-white hover:text-brand transition-colors"
                >
                  {c.name}
                </Link>
                <span className="ml-2 text-xs text-gray-600">{c.iso2}</span>
              </td>
              <td className={`px-4 py-3 text-right font-mono text-base font-bold ${scoreColor(c.overall_score)}`}>
                {c.overall_score.toFixed(1)}
              </td>
              <td className={`px-4 py-3 text-right font-mono ${scoreColor(c.macro_score)}`}>
                {c.macro_score.toFixed(1)}
              </td>
              <td className={`px-4 py-3 text-right font-mono ${scoreColor(c.market_score)}`}>
                {c.market_score.toFixed(1)}
              </td>
              <td className={`px-4 py-3 text-right font-mono ${scoreColor(c.stability_score)}`}>
                {c.stability_score.toFixed(1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
