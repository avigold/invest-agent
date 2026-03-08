import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { useUser } from "@/lib/auth";
import { apiJson } from "@/lib/api";
import { useMLModels } from "@/lib/queries";

interface ModelSummary {
  id: string;
  model_version: string;
  config: {
    n_observations?: number;
    n_winners?: number;
    base_rate?: number;
    fold_years?: number[];
    seed?: number;
    countries?: string[];
  };
  aggregate_metrics: {
    mean_auc?: number;
    std_auc?: number;
    n_folds?: number;
  };
  feature_importance: Record<string, number>;
  backtest_results: {
    total_return?: number;
    cagr?: number;
    sharpe?: number;
    max_drawdown?: number;
    hit_rate?: number;
    n_total_positions?: number;
  };
  created_at: string;
  job_id: string | null;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtPct(v: number | undefined): string {
  return v != null ? `${(v * 100).toFixed(1)}%` : "\u2014";
}

// Golden countries: 24, no India
const GOLDEN_COUNTRIES =
  "US,GB,CA,AU,DE,FR,JP,CH,SE,NL,KR,BR,ZA,SG,HK,NO,DK,FI,IL,NZ,TW,IE,BE,AT";

export default function Predictions() {
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const { data: models = [] } = useMLModels<ModelSummary[]>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Form state — golden model defaults
  const [seed, setSeed] = useState(32);
  const [countries, setCountries] = useState(GOLDEN_COUNTRIES);
  const [minDollarVolume, setMinDollarVolume] = useState(500000);
  const [maxReturnClip, setMaxReturnClip] = useState(10.0);
  const [returnThreshold, setReturnThreshold] = useState(0.20);
  const [relativeToCountry, setRelativeToCountry] = useState(true);
  const [halfLife, setHalfLife] = useState(7.0);
  const [minFiscalYear, setMinFiscalYear] = useState(2000);
  const [numLeaves, setNumLeaves] = useState(63);
  const [foldYears, setFoldYears] = useState("2018,2019,2020,2021,2022,2023");
  const [holdoutYear, setHoldoutYear] = useState(2024);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  const trainModel = async () => {
    setSubmitting(true);
    setError("");
    try {
      const job = await apiJson<{ id: string }>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "prediction_train",
          params: {
            seed,
            countries,
            min_dollar_volume: minDollarVolume,
            max_return_clip: maxReturnClip,
            return_threshold: returnThreshold,
            relative_to_country: relativeToCountry,
            half_life: halfLife,
            min_fiscal_year: minFiscalYear,
            num_leaves: numLeaves,
            fold_years: foldYears,
            holdout_year: holdoutYear,
          },
        }),
      });
      navigate(`/jobs/${job.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to submit training job");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading || !user) return null;

  const inputCls =
    "w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none";

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Predictive Models</h1>
        <p className="mt-1 text-sm text-gray-500">
          Train LightGBM models on 186 features from Parquet data to predict
          which companies will achieve exceptional returns
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Configuration */}
      <div className="mb-8 rounded-xl border border-gray-800 bg-gray-900/80 p-6">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Train New Model
        </h2>

        {/* Row 1: Data Filters */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Seed</label>
            <input
              type="number"
              min={1}
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
              className={inputCls}
            />
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Min Dollar Volume
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                step={100000}
                value={minDollarVolume}
                onChange={(e) => setMinDollarVolume(Number(e.target.value))}
                className={inputCls}
              />
            </div>
            <div className="mt-0.5 text-xs text-gray-600">
              ${(minDollarVolume / 1000).toFixed(0)}k/day
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Max Return Clip
            </label>
            <input
              type="number"
              min={1}
              max={100}
              step={1}
              value={maxReturnClip}
              onChange={(e) => setMaxReturnClip(Number(e.target.value))}
              className={inputCls}
            />
            <div className="mt-0.5 text-xs text-gray-600">
              Cap at +{(maxReturnClip * 100).toFixed(0)}%
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Num Leaves
            </label>
            <input
              type="number"
              min={7}
              max={255}
              value={numLeaves}
              onChange={(e) => setNumLeaves(Number(e.target.value))}
              className={inputCls}
            />
          </div>
        </div>

        {/* Row 2: Label & Weighting Config */}
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Return Threshold
            </label>
            <input
              type="number"
              min={0}
              max={5}
              step={0.05}
              value={returnThreshold}
              onChange={(e) => setReturnThreshold(Number(e.target.value))}
              className={inputCls}
            />
            <div className="mt-0.5 text-xs text-gray-600">
              Excess +{(returnThreshold * 100).toFixed(0)}% over country median
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Half-Life (years)
            </label>
            <input
              type="number"
              min={1}
              max={30}
              step={0.5}
              value={halfLife}
              onChange={(e) => setHalfLife(Number(e.target.value))}
              className={inputCls}
            />
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Min Fiscal Year
            </label>
            <input
              type="number"
              min={1990}
              max={2025}
              value={minFiscalYear}
              onChange={(e) => setMinFiscalYear(Number(e.target.value))}
              className={inputCls}
            />
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Options</label>
            <label className="flex items-center gap-2 mt-2">
              <input
                type="checkbox"
                checked={relativeToCountry}
                onChange={(e) => setRelativeToCountry(e.target.checked)}
                className="rounded border-gray-700 bg-gray-800 text-blue-500"
              />
              <span className="text-sm text-gray-300">
                Relative to country
              </span>
            </label>
          </div>
        </div>

        {/* Row 3: Countries */}
        <div className="mt-4">
          <label className="block text-xs text-gray-500 mb-1">
            Countries (ISO2, comma-separated)
          </label>
          <textarea
            value={countries}
            onChange={(e) => setCountries(e.target.value)}
            rows={2}
            className="w-full rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white font-mono focus:border-blue-500 focus:outline-none"
          />
          <div className="mt-0.5 text-xs text-gray-600">
            {countries.split(",").filter((c) => c.trim()).length} countries
          </div>
        </div>

        {/* Row 4: Fold Years & Holdout */}
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Fold Years (comma-separated)
            </label>
            <input
              type="text"
              value={foldYears}
              onChange={(e) => setFoldYears(e.target.value)}
              className={inputCls + " font-mono"}
            />
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Holdout Year
            </label>
            <input
              type="number"
              min={2015}
              max={2030}
              value={holdoutYear}
              onChange={(e) => setHoldoutYear(Number(e.target.value))}
              className={inputCls}
            />
          </div>
        </div>

        <div className="mt-6">
          <button
            onClick={trainModel}
            disabled={submitting}
            className="rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {submitting ? "Submitting..." : "Train Model"}
          </button>
          <p className="mt-2 text-xs text-gray-600">
            Trains on ~771k observations from Parquet data with walk-forward
            cross-validation, then scores the universe and runs backtesting.
          </p>
        </div>
      </div>

      {/* Past Models */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Trained Models ({models.length})
        </h2>
        <div className="overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/80">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="px-4 py-3">Model</th>
                <th className="px-4 py-3 text-right">AUC</th>
                <th className="px-4 py-3 text-right">Sharpe</th>
                <th className="px-4 py-3 text-right">Backtest Return</th>
                <th className="px-4 py-3 text-right">Hit Rate</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr
                  key={m.id}
                  className="border-b border-gray-800/50 hover:bg-white/[0.015] transition-colors"
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/predictions/${m.id}`}
                      className="font-medium text-blue-400 hover:text-blue-300"
                    >
                      {m.model_version}
                    </Link>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {m.config.n_observations ?? 0} obs, {m.config.n_winners ?? 0} winners
                      {m.config.seed != null && ` · seed ${m.config.seed}`}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-white">
                    {m.aggregate_metrics.mean_auc?.toFixed(3) ?? "\u2014"}
                    {m.aggregate_metrics.std_auc != null && (
                      <span className="ml-1 text-xs text-gray-500">
                        ±{m.aggregate_metrics.std_auc.toFixed(3)}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-white">
                    {m.backtest_results.sharpe?.toFixed(2) ?? "\u2014"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-white">
                    {fmtPct(m.backtest_results.total_return)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-white">
                    {fmtPct(m.backtest_results.hit_rate)}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{fmtDate(m.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/predictions/${m.id}`}
                      className="text-xs text-gray-500 hover:text-white"
                    >
                      View
                    </Link>
                  </td>
                </tr>
              ))}
              {models.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-600">
                    No models trained yet. Configure and train your first model above.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
