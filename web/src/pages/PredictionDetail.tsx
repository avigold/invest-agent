import { useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { useUser } from "@/lib/auth";
import { useMLModel, useMLModelScores } from "@/lib/queries";

interface ModelDetail {
  id: string;
  model_version: string;
  config: Record<string, unknown>;
  fold_metrics: Array<{
    year: number;
    n_train: number;
    n_test: number;
    n_train_pos: number;
    n_test_pos: number;
    auc: number;
  }>;
  aggregate_metrics: {
    mean_auc?: number;
    std_auc?: number;
    n_folds?: number;
    total_test_obs?: number;
    total_test_pos?: number;
  };
  feature_importance: Record<string, number>;
  backtest_results: {
    folds?: Array<{
      year: number;
      n_positions: number;
      portfolio_return: number;
      hit_rate: number;
      total_invested: number;
      positions: Array<{
        ticker: string;
        weight: number;
        probability: number;
        actual_return: number;
        hit: boolean;
      }>;
    }>;
    total_return?: number;
    cagr?: number;
    sharpe?: number;
    max_drawdown?: number;
    hit_rate?: number;
    n_total_positions?: number;
    n_total_hits?: number;
    calibration?: Array<{
      bucket: string;
      predicted_avg: number;
      actual_avg: number;
      count: number;
    }>;
  };
  platt_a: number;
  platt_b: number;
  created_at: string;
  job_id: string | null;
}

interface Score {
  id: string;
  ticker: string;
  company_name: string;
  probability: number;
  confidence_tier: string;
  kelly_fraction: number;
  suggested_weight: number;
  contributing_features: Record<string, { value: number; importance: number }>;
  feature_values: Record<string, number>;
  scored_at: string;
}

function fmtPct(v: number | undefined | null, decimals = 1): string {
  return v != null ? `${(v * 100).toFixed(decimals)}%` : "\u2014";
}

const TIER_COLORS: Record<string, string> = {
  high: "bg-green-900/50 text-green-300 border-green-800",
  medium: "bg-yellow-900/50 text-yellow-300 border-yellow-800",
  low: "bg-gray-800 text-gray-300 border-gray-700",
  negligible: "bg-gray-900 text-gray-500 border-gray-800",
};

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/60 px-4 py-3">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className="mt-1 text-xl font-bold text-white">{value}</div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  );
}

export default function PredictionDetail() {
  const { id } = useParams<{ id: string }>();
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const { data: model, error } = useMLModel<ModelDetail>(id || "");
  const { data: scoresData } = useMLModelScores<{ items: Score[]; total: number }>(id || "");
  const scores = scoresData?.items ?? [];
  const [showAllScores, setShowAllScores] = useState(false);

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [user, loading, navigate]);

  if (loading || !user) return null;
  if (error) {
    return (
      <div className="rounded border border-red-800 bg-red-900/30 px-4 py-2 text-sm text-red-300">
        {(error as Error).message}
      </div>
    );
  }
  if (!model) {
    return <div className="text-gray-500">Loading model...</div>;
  }

  const agg = model.aggregate_metrics;
  const bt = model.backtest_results;
  const fi = Object.entries(model.feature_importance)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15);
  const maxImp = fi.length > 0 ? fi[0][1] : 1;

  const visibleScores = showAllScores ? scores : scores.slice(0, 20);

  return (
    <div>
      {/* Header */}
      <div className="mb-6 flex items-center gap-3">
        <Link to="/predictions" className="text-gray-500 hover:text-white text-sm">
          &larr; Models
        </Link>
        <h1 className="text-2xl font-bold text-white">{model.model_version}</h1>
        <span className="text-sm text-gray-500">
          {new Date(model.created_at).toLocaleDateString()}
        </span>
      </div>

      {/* Performance Cards */}
      <div className="mb-6 grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard
          label="Mean AUC"
          value={agg.mean_auc?.toFixed(3) ?? "\u2014"}
          sub={agg.std_auc != null ? `±${agg.std_auc.toFixed(3)}` : undefined}
        />
        <StatCard label="Sharpe" value={bt.sharpe?.toFixed(2) ?? "\u2014"} />
        <StatCard label="Total Return" value={fmtPct(bt.total_return)} />
        <StatCard label="CAGR" value={fmtPct(bt.cagr)} />
        <StatCard label="Max Drawdown" value={fmtPct(bt.max_drawdown)} />
        <StatCard
          label="Hit Rate"
          value={fmtPct(bt.hit_rate)}
          sub={bt.n_total_hits != null ? `${bt.n_total_hits}/${bt.n_total_positions}` : undefined}
        />
      </div>

      {/* Walk-Forward Folds */}
      <div className="mb-6 rounded-xl border border-gray-800 bg-gray-900/80 p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Walk-Forward Folds
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="px-3 py-2">Year</th>
                <th className="px-3 py-2 text-right">Train</th>
                <th className="px-3 py-2 text-right">Test</th>
                <th className="px-3 py-2 text-right">AUC</th>
                <th className="px-3 py-2 text-right">Positions</th>
                <th className="px-3 py-2 text-right">Return</th>
                <th className="px-3 py-2 text-right">Hit Rate</th>
              </tr>
            </thead>
            <tbody>
              {model.fold_metrics.map((fold) => {
                const btFold = bt.folds?.find((f) => f.year === fold.year);
                return (
                  <tr key={fold.year} className="border-b border-gray-800/50">
                    <td className="px-3 py-2 font-mono text-white">{fold.year}</td>
                    <td className="px-3 py-2 text-right text-gray-400">
                      {fold.n_train} ({fold.n_train_pos} pos)
                    </td>
                    <td className="px-3 py-2 text-right text-gray-400">
                      {fold.n_test} ({fold.n_test_pos} pos)
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-white">
                      {fold.auc.toFixed(3)}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-400">
                      {btFold?.n_positions ?? "\u2014"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-white">
                      {btFold ? fmtPct(btFold.portfolio_return) : "\u2014"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-white">
                      {btFold ? fmtPct(btFold.hit_rate, 0) : "\u2014"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Feature Importance */}
      <div className="mb-6 rounded-xl border border-gray-800 bg-gray-900/80 p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Feature Importance (Gain)
        </h2>
        <div className="space-y-1.5">
          {fi.map(([name, imp]) => (
            <div key={name} className="flex items-center gap-3 min-w-0">
              <div className="w-40 flex-shrink-0 truncate text-xs text-gray-300">{name}</div>
              <div className="flex-1 min-w-0">
                <div className="h-4 w-full rounded bg-gray-800">
                  <div
                    className="h-4 rounded bg-blue-600/60"
                    style={{ width: `${(imp / maxImp) * 100}%` }}
                  />
                </div>
              </div>
              <div className="w-14 flex-shrink-0 text-right text-xs font-mono text-gray-400">
                {(imp * 100).toFixed(1)}%
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Calibration */}
      {bt.calibration && bt.calibration.length > 0 && (
        <div className="mb-6 rounded-xl border border-gray-800 bg-gray-900/80 p-5">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Calibration
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                  <th className="px-3 py-2">Bucket</th>
                  <th className="px-3 py-2 text-right">Predicted</th>
                  <th className="px-3 py-2 text-right">Actual</th>
                  <th className="px-3 py-2 text-right">Count</th>
                </tr>
              </thead>
              <tbody>
                {bt.calibration.map((c) => (
                  <tr key={c.bucket} className="border-b border-gray-800/50">
                    <td className="px-3 py-2 text-gray-300">{c.bucket}</td>
                    <td className="px-3 py-2 text-right font-mono text-white">
                      {fmtPct(c.predicted_avg)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-white">
                      {fmtPct(c.actual_avg)}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-400">{c.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Current Predictions */}
      <div className="mb-6 rounded-xl border border-gray-800 bg-gray-900/80 p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Current Predictions ({scores.length})
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs uppercase text-gray-500">
                <th className="px-3 py-2">Company</th>
                <th className="px-3 py-2 text-right">Probability</th>
                <th className="px-3 py-2">Confidence</th>
                <th className="px-3 py-2 text-right">Kelly</th>
                <th className="px-3 py-2 text-right">Weight</th>
                <th className="px-3 py-2">Top Features</th>
              </tr>
            </thead>
            <tbody>
              {visibleScores.map((s) => (
                <tr key={s.id} className="border-b border-gray-800/50 hover:bg-white/[0.015]">
                  <td className="px-3 py-2">
                    <Link
                      to={`/stocks/${s.ticker}`}
                      className="font-medium text-blue-400 hover:text-blue-300"
                    >
                      {s.ticker}
                    </Link>
                    <div className="text-xs text-gray-500">{s.company_name}</div>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-white">
                    {fmtPct(s.probability)}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-xs ${
                        TIER_COLORS[s.confidence_tier] ?? TIER_COLORS.negligible
                      }`}
                    >
                      {s.confidence_tier}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">
                    {fmtPct(s.kelly_fraction)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-400">
                    {s.suggested_weight > 0 ? fmtPct(s.suggested_weight) : "\u2014"}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(s.contributing_features || {})
                        .slice(0, 3)
                        .map(([feat, data]) => (
                          <span
                            key={feat}
                            className="inline-block rounded bg-gray-800 px-1.5 py-0.5 text-xs text-gray-400"
                            title={`${feat}: ${data.value} (importance: ${(data.importance * 100).toFixed(1)}%)`}
                          >
                            {feat.replace(/_/g, " ")}
                          </span>
                        ))}
                    </div>
                  </td>
                </tr>
              ))}
              {scores.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-600">
                    No scores available yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {scores.length > 20 && !showAllScores && (
          <button
            onClick={() => setShowAllScores(true)}
            className="mt-3 text-xs text-blue-400 hover:text-blue-300"
          >
            Show all {scores.length} predictions
          </button>
        )}
      </div>

      {/* Metadata */}
      <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4 text-xs text-gray-500">
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <span>Model: {model.model_version}</span>
          <span>Platt: A={model.platt_a.toFixed(4)}, B={model.platt_b.toFixed(4)}</span>
          <span>Folds: {agg.n_folds}</span>
          {model.job_id && (
            <Link to={`/jobs/${model.job_id}`} className="text-blue-400 hover:text-blue-300">
              Job log
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
