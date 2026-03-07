# app/predict/ — Two Independent Scoring Systems

This directory contains **two completely independent scoring systems**.
They must NEVER be conflated. Never import from one system into another.

## ML/Parquet System

LightGBM model trained on comprehensive Parquet data (186 features).
Portfolio: top-50 equal weight (2% each), deduped by company name.
Validated result: 84.5% avg annual return (2018-2024, seed 32).

| File | Purpose |
|------|---------|
| `parquet_scorer.py` | Score universe from Parquet using trained model |
| `parquet_dataset.py` | Load Parquet training data into ParquetDataset |
| `model.py` | LightGBM training, Platt scaling, serialisation (shared) |
| `backtest.py` | Walk-forward backtest evaluation |

## Deterministic System

Fundamentals-based scoring from CompanyScore database data (22 features).
Portfolio: Kelly criterion with sector/position constraints.

| File | Purpose |
|------|---------|
| `scorer.py` | Score current universe from database |
| `strategy.py` | Kelly sizing, portfolio constraints |
| `features.py` | 22 fundamental + price features |
| `dataset.py` | Build feature matrix from observations |

## Shared

| File | Purpose |
|------|---------|
| `model.py` | Model training, Platt scaling, serialisation |

## Rules

- Before modifying any file in this directory, check this README first.
- Never import ML/Parquet files from deterministic files or vice versa.
- Never apply ML methodology (top-50 equal weight) to deterministic files.
- Never apply deterministic methodology (Kelly, constraints) to ML files.
- Never modify `model.py` serialise/deserialise without explicit user approval.
