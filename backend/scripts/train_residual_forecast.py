#!/usr/bin/env python3
"""Offline training pipeline for residual forecast correction.

This script:
1) Builds residual targets: BG_real_h - baseline_forecast_h.
2) Trains CatBoost quantile regressors (p10/p50/p90) per horizon.
3) Performs rolling backtesting and compares vs baseline.
4) Persists models, metrics, and data range.
5) Flags ml_ready based on metric thresholds (not sample count).
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sqlalchemy import create_engine

HORIZONS_MIN = [30, 60, 120, 240, 360]
QUANTILES = [0.1, 0.5, 0.9]

NUMERIC_FEATURES = [
    "bg_mgdl",
    "bg_age_min",
    "iob_u",
    "cob_g",
    "basal_active_u",
    "basal_latest_u",
    "basal_latest_age_min",
    "basal_total_24h",
    "basal_total_48h",
    "bolus_total_3h",
    "bolus_total_6h",
    "carbs_total_3h",
    "carbs_total_6h",
    "exercise_minutes_6h",
    "exercise_minutes_24h",
    "hour_of_day",
    "day_of_week",
    "source_ns_enabled",
    "source_ns_treatments_count",
    "source_db_treatments_count",
    "source_overlap_count",
    "source_conflict_count",
]

CATEGORICAL_FEATURES = [
    "trend",
    "iob_status",
    "cob_status",
    "source_consistency_status",
]


@dataclass
class Metrics:
    mae: float
    rmse: float
    bias: float


@dataclass
class ErrorStats:
    count: int
    sum_abs: float
    sum_sq: float
    sum: float


@dataclass
class SplitMetrics:
    horizon_min: int
    split_start: str
    split_end: str
    baseline: Metrics
    model: Metrics
    baseline_stats: ErrorStats
    model_stats: ErrorStats


@dataclass
class HorizonSummary:
    horizon_min: int
    baseline: Metrics
    model: Metrics
    ml_ready: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train residual CatBoost models offline.")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL"), help="Database URL")
    parser.add_argument("--output-dir", default="backend/ml_training_output", help="Output directory")
    parser.add_argument("--user-id", default=None, help="Optional user_id filter")
    parser.add_argument("--train-window-days", type=int, default=14)
    parser.add_argument("--test-window-days", type=int, default=2)
    parser.add_argument("--step-days", type=int, default=2)
    parser.add_argument("--include-flagged", action="store_true", help="Include flagged rows")
    parser.add_argument("--mae-improvement", type=float, default=0.05, help="Required MAE improvement")
    parser.add_argument("--rmse-improvement", type=float, default=0.05, help="Required RMSE improvement")
    parser.add_argument("--bias-threshold", type=float, default=5.0, help="Abs bias threshold")
    parser.add_argument("--random-seed", type=int, default=42)
    return parser.parse_args()


def load_data(db_url: str, user_id: str | None, include_flagged: bool) -> pd.DataFrame:
    if not db_url:
        raise ValueError("DATABASE_URL is required for offline training.")

    engine = create_engine(db_url)
    query = """
        SELECT
            feature_time,
            user_id,
            bg_mgdl,
            trend,
            bg_age_min,
            iob_u,
            cob_g,
            iob_status,
            cob_status,
            basal_active_u,
            basal_latest_u,
            basal_latest_age_min,
            basal_total_24h,
            basal_total_48h,
            bolus_total_3h,
            bolus_total_6h,
            carbs_total_3h,
            carbs_total_6h,
            exercise_minutes_6h,
            exercise_minutes_24h,
            baseline_bg_30m,
            baseline_bg_60m,
            baseline_bg_120m,
            baseline_bg_240m,
            baseline_bg_360m,
            source_ns_enabled,
            source_ns_treatments_count,
            source_db_treatments_count,
            source_overlap_count,
            source_conflict_count,
            source_consistency_status,
            flag_bg_missing,
            flag_bg_stale,
            flag_iob_unavailable,
            flag_cob_unavailable,
            flag_source_conflict
        FROM ml_training_data_v2
    """
    params: dict[str, str] = {}
    if user_id:
        query += " WHERE user_id = :user_id"
        params["user_id"] = user_id
    df = pd.read_sql_query(query, engine, params=params)
    df["feature_time"] = pd.to_datetime(df["feature_time"], utc=True)
    if not include_flagged:
        df = df[
            (~df["flag_bg_missing"].fillna(False))
            & (~df["flag_bg_stale"].fillna(False))
            & (~df["flag_iob_unavailable"].fillna(False))
            & (~df["flag_cob_unavailable"].fillna(False))
            & (~df["flag_source_conflict"].fillna(False))
        ]
    return df.sort_values("feature_time").reset_index(drop=True)


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hour_of_day"] = df["feature_time"].dt.hour
    df["day_of_week"] = df["feature_time"].dt.dayofweek
    return df


def build_horizon_dataset(df: pd.DataFrame, horizon_min: int) -> pd.DataFrame:
    baseline_col = f"baseline_bg_{horizon_min}m"
    if baseline_col not in df.columns:
        raise ValueError(f"Missing column {baseline_col}")

    future = df[["feature_time", "bg_mgdl"]].rename(columns={"bg_mgdl": "future_bg"})
    future = future.copy()
    future["feature_time"] = future["feature_time"] - timedelta(minutes=horizon_min)

    merged = df.merge(future, on="feature_time", how="inner")
    merged = merged.dropna(subset=[baseline_col, "future_bg"])
    merged["target_residual"] = merged["future_bg"] - merged[baseline_col]
    merged["baseline_error"] = merged["future_bg"] - merged[baseline_col]
    return merged


def stats_from_errors(errors: np.ndarray) -> ErrorStats:
    return ErrorStats(
        count=int(errors.size),
        sum_abs=float(np.sum(np.abs(errors))),
        sum_sq=float(np.sum(np.square(errors))),
        sum=float(np.sum(errors)),
    )


def metrics_from_stats(stats: ErrorStats) -> Metrics:
    if stats.count == 0:
        return Metrics(mae=float("nan"), rmse=float("nan"), bias=float("nan"))
    mae = stats.sum_abs / stats.count
    rmse = np.sqrt(stats.sum_sq / stats.count)
    bias = stats.sum / stats.count
    return Metrics(mae=float(mae), rmse=float(rmse), bias=float(bias))


def rolling_splits(
    times: pd.Series,
    train_window: timedelta,
    test_window: timedelta,
    step: timedelta,
) -> Iterable[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    min_time = times.min()
    max_time = times.max()
    train_start = min_time
    train_end = train_start + train_window
    while train_end + test_window <= max_time:
        test_end = train_end + test_window
        yield train_start, train_end, test_end
        train_start += step
        train_end = train_start + train_window


def prepare_features(df: pd.DataFrame, horizon_min: int) -> tuple[pd.DataFrame, list[int]]:
    baseline_col = f"baseline_bg_{horizon_min}m"
    features = df.copy()
    features[baseline_col] = features[baseline_col].astype(float)
    feature_cols = NUMERIC_FEATURES + [baseline_col] + CATEGORICAL_FEATURES
    feature_cols = [col for col in feature_cols if col in features.columns]
    cat_indices = [feature_cols.index(col) for col in CATEGORICAL_FEATURES if col in feature_cols]

    for col in CATEGORICAL_FEATURES:
        if col in features.columns:
            features[col] = features[col].fillna("unknown").astype(str)
    for col in feature_cols:
        if col not in CATEGORICAL_FEATURES:
            features[col] = pd.to_numeric(features[col], errors="coerce")

    return features[feature_cols], cat_indices


def fill_missing(train_df: pd.DataFrame, test_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_df = train_df.copy()
    test_df = test_df.copy()
    numeric_cols = [col for col in train_df.columns if col not in CATEGORICAL_FEATURES]
    medians = train_df[numeric_cols].median()
    train_df[numeric_cols] = train_df[numeric_cols].fillna(medians)
    test_df[numeric_cols] = test_df[numeric_cols].fillna(medians)
    for col in CATEGORICAL_FEATURES:
        if col in train_df.columns:
            train_df[col] = train_df[col].fillna("unknown")
            test_df[col] = test_df[col].fillna("unknown")
    return train_df, test_df


def train_quantile_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    cat_indices: list[int],
    quantile: float,
    random_seed: int,
) -> CatBoostRegressor:
    model = CatBoostRegressor(
        loss_function=f"Quantile:alpha={quantile}",
        depth=6,
        learning_rate=0.1,
        iterations=600,
        random_seed=random_seed,
        verbose=False,
    )
    model.fit(X_train, y_train, cat_features=cat_indices)
    return model


def evaluate_split(
    df: pd.DataFrame,
    horizon_min: int,
    train_end: pd.Timestamp,
    test_end: pd.Timestamp,
    train_window_start: pd.Timestamp,
    random_seed: int,
) -> SplitMetrics:
    train_mask = (df["feature_time"] >= train_window_start) & (df["feature_time"] < train_end)
    test_mask = (df["feature_time"] >= train_end) & (df["feature_time"] < test_end)

    train_df = df.loc[train_mask]
    test_df = df.loc[test_mask]
    X_train, cat_indices = prepare_features(train_df, horizon_min)
    X_test, _ = prepare_features(test_df, horizon_min)
    X_train, X_test = fill_missing(X_train, X_test)

    y_train = train_df["target_residual"]

    model = train_quantile_model(X_train, y_train, cat_indices, 0.5, random_seed)
    residual_pred = model.predict(X_test)

    baseline_errors = test_df["baseline_error"].to_numpy()
    model_errors = baseline_errors - residual_pred

    baseline_stats = stats_from_errors(baseline_errors)
    model_stats = stats_from_errors(model_errors)

    return SplitMetrics(
        horizon_min=horizon_min,
        split_start=train_end.isoformat(),
        split_end=test_end.isoformat(),
        baseline=metrics_from_stats(baseline_stats),
        model=metrics_from_stats(model_stats),
        baseline_stats=baseline_stats,
        model_stats=model_stats,
    )


def summarize_splits(splits: list[SplitMetrics]) -> tuple[Metrics, Metrics]:
    if not splits:
        return (
            Metrics(mae=float("nan"), rmse=float("nan"), bias=float("nan")),
            Metrics(mae=float("nan"), rmse=float("nan"), bias=float("nan")),
        )

    baseline_stats = ErrorStats(count=0, sum_abs=0.0, sum_sq=0.0, sum=0.0)
    model_stats = ErrorStats(count=0, sum_abs=0.0, sum_sq=0.0, sum=0.0)

    for split in splits:
        baseline_stats.count += split.baseline_stats.count
        baseline_stats.sum_abs += split.baseline_stats.sum_abs
        baseline_stats.sum_sq += split.baseline_stats.sum_sq
        baseline_stats.sum += split.baseline_stats.sum

        model_stats.count += split.model_stats.count
        model_stats.sum_abs += split.model_stats.sum_abs
        model_stats.sum_sq += split.model_stats.sum_sq
        model_stats.sum += split.model_stats.sum

    return metrics_from_stats(baseline_stats), metrics_from_stats(model_stats)


def compute_ml_ready(
    baseline: Metrics,
    model: Metrics,
    mae_improvement: float,
    rmse_improvement: float,
    bias_threshold: float,
) -> bool:
    return (
        model.mae <= baseline.mae * (1 - mae_improvement)
        and model.rmse <= baseline.rmse * (1 - rmse_improvement)
        and abs(model.bias) <= bias_threshold
    )


def main() -> None:
    args = parse_args()
    df_raw = load_data(args.db_url, args.user_id, args.include_flagged)
    if df_raw.empty:
        raise RuntimeError("No training data found in ml_training_data_v2.")

    df_raw = add_time_features(df_raw)
    data_start = df_raw["feature_time"].min().isoformat()
    data_end = df_raw["feature_time"].max().isoformat()

    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    version = pd.Timestamp.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / f"residual_{version}"
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "version": version,
        "data_range": {"start": data_start, "end": data_end},
        "horizons": {},
        "mae_improvement": args.mae_improvement,
        "rmse_improvement": args.rmse_improvement,
        "bias_threshold": args.bias_threshold,
    }

    split_results: list[SplitMetrics] = []
    horizon_summaries: list[HorizonSummary] = []

    train_window = timedelta(days=args.train_window_days)
    test_window = timedelta(days=args.test_window_days)
    step = timedelta(days=args.step_days)

    for horizon in HORIZONS_MIN:
        df_h = build_horizon_dataset(df_raw, horizon)
        if df_h.empty:
            continue

        splits = []
        for train_start, train_end, test_end in rolling_splits(
            df_h["feature_time"], train_window, test_window, step
        ):
            split_metric = evaluate_split(df_h, horizon, train_end, test_end, train_start, args.random_seed)
            splits.append(split_metric)
        split_results.extend(splits)

        baseline_metrics, model_metrics = summarize_splits(splits)
        ml_ready = compute_ml_ready(
            baseline_metrics,
            model_metrics,
            args.mae_improvement,
            args.rmse_improvement,
            args.bias_threshold,
        )
        horizon_summaries.append(
            HorizonSummary(
                horizon_min=horizon,
                baseline=baseline_metrics,
                model=model_metrics,
                ml_ready=ml_ready,
            )
        )

        # Train final models on full dataset
        X_full, cat_indices = prepare_features(df_h, horizon)
        X_full, _ = fill_missing(X_full, X_full)
        y_full = df_h["target_residual"]

        for quantile in QUANTILES:
            model = train_quantile_model(X_full, y_full, cat_indices, quantile, args.random_seed)
            model_path = output_dir / f"catboost_residual_{horizon}m_p{int(quantile*100)}.cbm"
            model.save_model(model_path)

        report["horizons"][str(horizon)] = {
            "baseline": baseline_metrics.__dict__,
            "model": model_metrics.__dict__,
            "ml_ready": ml_ready,
        }

    metrics_path = output_dir / "metrics.json"
    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    split_rows = [
        {
            "horizon_min": split.horizon_min,
            "split_start": split.split_start,
            "split_end": split.split_end,
            "baseline_mae": split.baseline.mae,
            "baseline_rmse": split.baseline.rmse,
            "baseline_bias": split.baseline.bias,
            "model_mae": split.model.mae,
            "model_rmse": split.model.rmse,
            "model_bias": split.model.bias,
        }
        for split in split_results
    ]
    if split_rows:
        pd.DataFrame(split_rows).to_csv(output_dir / "backtest_splits.csv", index=False)

    summary_rows = [
        {
            "horizon_min": summary.horizon_min,
            "baseline_mae": summary.baseline.mae,
            "baseline_rmse": summary.baseline.rmse,
            "baseline_bias": summary.baseline.bias,
            "model_mae": summary.model.mae,
            "model_rmse": summary.model.rmse,
            "model_bias": summary.model.bias,
            "ml_ready": summary.ml_ready,
        }
        for summary in horizon_summaries
    ]
    if summary_rows:
        pd.DataFrame(summary_rows).to_csv(output_dir / "backtest_summary.csv", index=False)

    report_md = output_dir / "report.md"
    with report_md.open("w", encoding="utf-8") as f:
        f.write("# Residual Forecast Training Report\n\n")
        f.write(f"Version: `{version}`\n\n")
        f.write(f"Data range: `{data_start}` → `{data_end}`\n\n")
        f.write("## Horizon Summary\n\n")
        for summary in horizon_summaries:
            f.write(f"### {summary.horizon_min} min\n")
            f.write(f"- Baseline MAE: {summary.baseline.mae:.2f}\n")
            f.write(f"- Baseline RMSE: {summary.baseline.rmse:.2f}\n")
            f.write(f"- Baseline Bias: {summary.baseline.bias:.2f}\n")
            f.write(f"- Model MAE: {summary.model.mae:.2f}\n")
            f.write(f"- Model RMSE: {summary.model.rmse:.2f}\n")
            f.write(f"- Model Bias: {summary.model.bias:.2f}\n")
            f.write(f"- ml_ready: {summary.ml_ready}\n\n")

    metadata_path = output_dir / "metadata.json"
    metadata = {
        "version": version,
        "data_range": {"start": data_start, "end": data_end},
        "features": {
            "numeric": NUMERIC_FEATURES,
            "categorical": CATEGORICAL_FEATURES,
        },
        "horizons": HORIZONS_MIN,
        "quantiles": QUANTILES,
        "ml_ready_logic": {
            "mae_improvement": args.mae_improvement,
            "rmse_improvement": args.rmse_improvement,
            "bias_threshold": args.bias_threshold,
        },
    }
    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"✅ Training artifacts saved to: {output_dir}")


if __name__ == "__main__":
    main()
