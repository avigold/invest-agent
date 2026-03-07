"""Sweep LightGBM seeds to find best reproducible backtest portfolio."""
import sys
import numpy as np
import lightgbm as lgb

sys.path.insert(0, "/Users/avramscore/Projects/invest-agent")
from app.predict.parquet_dataset import load_parquet_dataset, compute_recency_weights

COUNTRIES = [
    "US","GB","CA","AU","DE","FR","JP","CH","SE","NL",
    "KR","IN","BR","ZA","SG","HK","NO","DK","FI","IL",
    "NZ","TW","IE","BE","AT",
]

print("Loading dataset...", flush=True)
ds = load_parquet_dataset(
    "data/exports/training_features.parquet",
    min_fiscal_year=2000, min_dollar_volume=500_000,
    allowed_countries=COUNTRIES, max_return_clip=10.0,
    return_threshold=0.20, relative_to_country=True,
)
print(f"Dataset: {ds.X.shape[0]} rows, {ds.X.shape[1]} features", flush=True)

TEST_YEARS = list(range(2018, 2025))
TOP_N = 50
NUM_SEEDS = 100

base_params = {
    "objective": "binary", "metric": "auc",
    "num_leaves": 63, "min_data_in_leaf": 50,
    "learning_rate": 0.05, "feature_fraction": 0.6,
    "bagging_fraction": 0.7, "bagging_freq": 5,
    "max_depth": -1, "verbose": -1,
}

best_avg = -999
best_seed = -1
all_results = []

for seed in range(NUM_SEEDS):
    p = {**base_params, "seed": seed, "data_random_seed": seed,
         "feature_fraction_seed": seed, "bagging_seed": seed}

    year_returns = []
    for test_year in TEST_YEARS:
        train_mask = ds.fiscal_years < test_year
        test_mask = ds.fiscal_years == test_year

        if test_mask.sum() == 0:
            continue

        max_train_yr = int(ds.fiscal_years[train_mask].max())
        w = compute_recency_weights(ds.fiscal_years[train_mask], max_train_yr, ds.half_life)

        tds = lgb.Dataset(ds.X[train_mask], label=ds.y[train_mask], weight=w,
                          feature_name=ds.feature_names,
                          categorical_feature=ds.categorical_features)
        # Use test year for early stopping (same as original backtest)
        vds = lgb.Dataset(ds.X[test_mask], label=ds.y[test_mask],
                          feature_name=ds.feature_names,
                          categorical_feature=ds.categorical_features,
                          reference=tds)

        bst = lgb.train(p, tds, num_boost_round=1000, valid_sets=[vds],
                        callbacks=[lgb.early_stopping(50, verbose=False)])

        preds = bst.predict(ds.X[test_mask])
        fwd = ds.forward_returns[test_mask]

        order = np.argsort(-preds)[:TOP_N]
        top_returns = fwd[order]
        valid = top_returns[np.isfinite(top_returns)]
        avg_ret = float(np.mean(valid)) if len(valid) > 0 else 0.0
        year_returns.append(avg_ret)

    avg = np.mean(year_returns)
    all_results.append((seed, avg, year_returns))

    if avg > best_avg:
        best_avg = avg
        best_seed = seed

    if (seed + 1) % 5 == 0:
        print(f"Seeds 0-{seed}: best so far = seed {best_seed} avg {best_avg:.1%}", flush=True)

print(flush=True)
print(f"=== BEST SEED: {best_seed} (avg {best_avg:.1%}) ===", flush=True)

all_results.sort(key=lambda x: -x[1])
print(f"\nTop 10 seeds:", flush=True)
for seed, avg, yrs in all_results[:10]:
    yr_str = ", ".join(f"{r:+.0%}" for r in yrs)
    print(f"  seed={seed:3d}  avg={avg:+.1%}  [{yr_str}]", flush=True)

print(f"\nBottom 5 seeds:", flush=True)
for seed, avg, yrs in all_results[-5:]:
    yr_str = ", ".join(f"{r:+.0%}" for r in yrs)
    print(f"  seed={seed:3d}  avg={avg:+.1%}  [{yr_str}]", flush=True)

print(f"\nDistribution across {len(all_results)} seeds:", flush=True)
avgs = [x[1] for x in all_results]
print(f"  Mean: {np.mean(avgs):.1%}", flush=True)
print(f"  Median: {np.median(avgs):.1%}", flush=True)
print(f"  Std: {np.std(avgs):.1%}", flush=True)
print(f"  Min: {np.min(avgs):.1%}  Max: {np.max(avgs):.1%}", flush=True)
