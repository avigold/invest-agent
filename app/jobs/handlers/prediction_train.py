"""Handler for prediction_train job command.

Trains a LightGBM model to predict 4x winners using walk-forward CV,
runs backtesting, scores the current universe, and stores everything.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Company, PredictionModel, PredictionScore
from app.predict.backtest import backtest_to_dict, run_backtest
from app.predict.dataset import build_dataset
from app.predict.model import MODEL_VERSION, train_walk_forward
from app.predict.scorer import confidence_tier, score_current_universe
from app.predict.strategy import build_portfolio, kelly_fraction
from app.screen.forward_scanner import generate_observations
from app.screen.fundamentals_snapshot import fetch_fundamentals_for_observations
from app.screen.price_history import fetch_extended_prices

if TYPE_CHECKING:
    from app.jobs.registry import LiveJob


def _log(job: "LiveJob", msg: str) -> None:
    job.log_lines.append(msg)
    job.queue.put(msg)


async def prediction_train_handler(
    job: "LiveJob",
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Train a prediction model end-to-end."""
    params = job.params
    return_threshold = float(params.get("return_threshold", 3.0))
    window_years = int(params.get("window_years", 5))
    lookback_years = int(params.get("lookback_years", 20))
    include_fundamentals = params.get("include_fundamentals", True)

    today = datetime.now(tz=timezone.utc).date()
    start_date = f"{today.year - lookback_years}-01-01"
    end_date = str(today)

    _log(job, "=== Prediction Model Training ===")
    _log(job, f"  Winner threshold: {return_threshold * 100:.0f}% ({return_threshold + 1:.0f}x)")
    _log(job, f"  Forward window: {window_years} years")
    _log(job, f"  Lookback: {lookback_years} years ({start_date} to {end_date})")

    async with session_factory() as db:
        # Phase 1: Load universe
        _log(job, "\n--- Loading universe ---")
        result = await db.execute(select(Company))
        companies = list(result.scalars().all())
        tickers = [c.ticker for c in companies]
        ticker_metadata = {
            c.ticker: {
                "name": c.name,
                "country_iso2": c.country_iso2,
                "gics_code": c.gics_code or "",
            }
            for c in companies
        }
        _log(job, f"Universe: {len(tickers)} companies")

        # Phase 2: Fetch price histories
        _log(job, "\n--- Fetching price histories ---")
        prices = await fetch_extended_prices(
            tickers, start_date, end_date,
            log_fn=lambda msg: _log(job, msg),
        )
        _log(job, f"Got price data for {len(prices)}/{len(tickers)} tickers")

        # Phase 3: Generate observations
        _log(job, "\n--- Generating observations ---")
        observations = generate_observations(
            prices, ticker_metadata,
            window_years=window_years,
            return_threshold=return_threshold,
            log_fn=lambda msg: _log(job, msg),
        )

        if len(observations) < 50:
            _log(job, f"ERROR: Only {len(observations)} observations — need at least 50")
            job.status = "failed"
            return

        # Phase 4: Attach fundamentals (optional)
        if include_fundamentals:
            _log(job, "\n--- Fetching fundamentals ---")
            await fetch_fundamentals_for_observations(
                observations,
                log_fn=lambda msg: _log(job, msg),
            )

        # Phase 5: Build feature matrix
        _log(job, "\n--- Building feature matrix ---")
        dataset = build_dataset(observations, prices)
        _log(job, f"Dataset: {dataset.n_observations} observations, "
                   f"{dataset.n_features} features, "
                   f"{dataset.n_winners} winners ({dataset.base_rate:.1%} base rate)")

        if dataset.n_winners < 5:
            _log(job, "ERROR: Fewer than 5 winners — model cannot learn")
            job.status = "failed"
            return

        # Phase 6: Train model with walk-forward CV
        _log(job, "\n--- Training model (walk-forward CV) ---")
        model = train_walk_forward(
            dataset,
            log_fn=lambda msg: _log(job, msg),
        )

        agg = model.aggregate_metrics
        _log(job, f"\nAggregate results:")
        _log(job, f"  Mean AUC: {agg.get('mean_auc', 0):.3f} +/- {agg.get('std_auc', 0):.3f}")
        _log(job, f"  Folds: {agg.get('n_folds', 0)}")
        _log(job, f"  Total test observations: {agg.get('total_test_obs', 0)}")

        # Phase 7: Backtest
        _log(job, "\n--- Running backtest ---")
        bt_results = run_backtest(model, dataset)
        _log(job, f"Backtest results:")
        _log(job, f"  Total return: {bt_results.total_return:.1%}")
        _log(job, f"  CAGR: {bt_results.cagr:.1%}")
        _log(job, f"  Sharpe: {bt_results.sharpe:.2f}")
        _log(job, f"  Max drawdown: {bt_results.max_drawdown:.1%}")
        _log(job, f"  Hit rate: {bt_results.hit_rate:.1%} ({bt_results.n_total_hits}/{bt_results.n_total_positions})")

        for fold in bt_results.folds:
            _log(job, f"  Year {fold.year}: return={fold.portfolio_return:.1%}, "
                       f"positions={fold.n_positions}, hit_rate={fold.hit_rate:.0%}")

        # Phase 8: Score current universe
        _log(job, "\n--- Scoring current universe ---")
        scored = await score_current_universe(
            db, model,
            log_fn=lambda msg: _log(job, msg),
        )

        # Build suggested portfolio
        pred_dicts = [
            {"ticker": s.ticker, "probability": s.probability, "sector": "Unknown"}
            for s in scored
        ]
        portfolio = build_portfolio(pred_dicts)
        weight_map = {p.ticker: p.weight for p in portfolio}

        _log(job, f"\nTop predictions:")
        for s in scored[:10]:
            w = weight_map.get(s.ticker, 0)
            _log(job, f"  {s.ticker} ({s.company_name}): "
                       f"p={s.probability:.3f} ({s.confidence}), "
                       f"kelly={s.kelly:.3f}, weight={w:.1%}")

        # Phase 9: Store model and scores
        _log(job, "\n--- Storing model and scores ---")

        # Serialize fold metrics for storage
        fold_metrics_json = [
            {
                "year": fr.year,
                "n_train": fr.n_train,
                "n_test": fr.n_test,
                "n_train_pos": fr.n_train_pos,
                "n_test_pos": fr.n_test_pos,
                "auc": round(fr.auc, 4),
            }
            for fr in model.fold_results
        ]

        pred_model = PredictionModel(
            user_id=job.user_id,
            job_id=job.id,
            model_version=MODEL_VERSION,
            config=model.train_config,
            fold_metrics=fold_metrics_json,
            aggregate_metrics=agg,
            feature_importance=model.feature_importance,
            backtest_results=backtest_to_dict(bt_results),
            model_blob=model.serialize(),
            platt_a=model.platt_a,
            platt_b=model.platt_b,
        )
        db.add(pred_model)
        await db.flush()  # Get the model ID

        # Store individual scores
        for s in scored:
            w = weight_map.get(s.ticker, 0)
            ps = PredictionScore(
                model_id=pred_model.id,
                user_id=job.user_id,
                ticker=s.ticker,
                company_name=s.company_name,
                probability=s.probability,
                confidence_tier=s.confidence,
                kelly_fraction=s.kelly,
                suggested_weight=round(w, 4),
                contributing_features=s.contributing_features,
                feature_values=s.feature_values,
                job_id=job.id,
            )
            db.add(ps)

        await db.commit()

        _log(job, f"\nModel saved: {pred_model.id}")
        _log(job, f"Scores saved: {len(scored)} companies")
        _log(job, "\n=== Training Complete ===")
        _log(job, f"AUC: {agg.get('mean_auc', 0):.3f}")
        _log(job, f"Backtest Sharpe: {bt_results.sharpe:.2f}")
        _log(job, f"Top pick: {scored[0].ticker} (p={scored[0].probability:.3f})" if scored else "No scores")
        _log(job, "Done.")
