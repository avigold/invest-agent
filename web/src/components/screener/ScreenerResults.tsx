import { Link } from "react-router-dom";

export interface ScreenerRow {
  ticker: string;
  company_name: string;
  country: string;
  sector: string;
  pe_ratio: number | null;
  pb_ratio: number | null;
  roe: number | null;
  net_margin: number | null;
  revenue_growth: number | null;
  probability: number;
  det_classification: string;
  ml_classification: string;
  [key: string]: unknown;
}

interface Column {
  key: string;
  label: string;
  format?: (v: unknown) => string;
  align?: "left" | "right";
}

const fmtPct = (v: unknown) => (v != null ? `${((v as number) * 100).toFixed(1)}%` : "\u2014");
const fmtX = (v: unknown) => (v != null ? `${(v as number).toFixed(1)}x` : "\u2014");
const fmtProb = (v: unknown) => (v != null ? `${((v as number) * 100).toFixed(0)}%` : "\u2014");
const fmtStr = (v: unknown) => (v != null ? String(v) : "\u2014");

const COLUMNS: Column[] = [
  { key: "ticker", label: "Ticker", align: "left" },
  { key: "company_name", label: "Name", align: "left" },
  { key: "country", label: "Country", align: "left" },
  { key: "sector", label: "Sector", align: "left" },
  { key: "pe_ratio", label: "P/E", format: fmtX, align: "right" },
  { key: "roe", label: "ROE", format: fmtPct, align: "right" },
  { key: "revenue_growth", label: "Rev Growth", format: fmtPct, align: "right" },
  { key: "probability", label: "ML Prob", format: fmtProb, align: "right" },
  { key: "det_classification", label: "Class.", format: fmtStr, align: "left" },
];

interface Props {
  rows: ScreenerRow[];
  total: number;
  sortBy: string;
  sortDesc: boolean;
  onSort: (field: string) => void;
  loading?: boolean;
}

function classificationBadge(val: string) {
  const colours: Record<string, string> = {
    Buy: "bg-green-900/50 text-green-400",
    Hold: "bg-yellow-900/50 text-yellow-400",
    Sell: "bg-red-900/50 text-red-400",
  };
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${colours[val] ?? "bg-gray-800 text-gray-400"}`}>
      {val}
    </span>
  );
}

export default function ScreenerResults({ rows, total, sortBy, sortDesc, onSort, loading }: Props) {
  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-gray-400">
          {loading ? "Screening..." : `${total} ${total === 1 ? "company" : "companies"} match`}
        </p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  onClick={() => onSort(col.key)}
                  className={`cursor-pointer px-4 py-3 hover:text-white transition-colors ${
                    col.align === "right" ? "text-right" : ""
                  }`}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.label}
                    {sortBy === col.key && (
                      <span className="text-blue-400">{sortDesc ? "\u25BC" : "\u25B2"}</span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.ticker}
                className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors"
              >
                {COLUMNS.map((col) => {
                  const val = row[col.key];
                  if (col.key === "ticker") {
                    return (
                      <td key={col.key} className="px-4 py-3">
                        <Link
                          to={`/stocks/${row.ticker}`}
                          className="font-medium text-blue-400 hover:text-blue-300"
                        >
                          {row.ticker}
                        </Link>
                      </td>
                    );
                  }
                  if (col.key === "company_name") {
                    return (
                      <td key={col.key} className="max-w-[200px] truncate px-4 py-3 text-white">
                        {row.company_name}
                      </td>
                    );
                  }
                  if (col.key === "det_classification") {
                    return (
                      <td key={col.key} className="px-4 py-3">
                        {classificationBadge(val as string)}
                      </td>
                    );
                  }
                  const formatted = col.format ? col.format(val) : String(val ?? "\u2014");
                  return (
                    <td
                      key={col.key}
                      className={`px-4 py-3 font-mono ${
                        col.align === "right" ? "text-right" : ""
                      } ${val == null ? "text-gray-600" : "text-white"}`}
                    >
                      {formatted}
                    </td>
                  );
                })}
              </tr>
            ))}
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={COLUMNS.length} className="px-4 py-12 text-center text-gray-600">
                  No companies match your filters. Try adjusting or removing some filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
