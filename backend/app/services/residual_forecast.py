from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

from catboost import CatBoostRegressor, Pool

from app.models.basal import BasalEntry
from app.models.forecast import ForecastPoint
from app.models.settings import UserSettings
from app.models.treatment import Treatment
from app.services.iob import compute_cob_from_sources, compute_iob_from_sources
from app.services.store import DataStore
from app.services.nightscout_secrets_service import NSConfig

logger = logging.getLogger(__name__)

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
class ResidualModelBundle:
    root: Path
    models: dict[tuple[int, float], CatBoostRegressor]
    ml_ready: bool
    metrics: Optional[dict]
    confidence_score: Optional[float]


@dataclass
class ResidualAdjustmentResult:
    applied: bool
    adjusted_series: list[ForecastPoint]
    ml_prediction: Optional[dict[int, float]]
    ml_band: Optional[dict[int, dict[str, float]]]
    confidence_score: Optional[float]


def _resolve_model_root() -> Path:
    override = os.getenv("RESIDUAL_MODEL_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "ml_training_output"


def _find_latest_model_dir(root: Path) -> Optional[Path]:
    if not root.exists():
        return None
    candidates = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("residual_")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.name)


def _load_metrics(metrics_path: Path) -> Optional[dict]:
    if not metrics_path.exists():
        return None
    try:
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _compute_confidence(metrics: Optional[dict]) -> Optional[float]:
    if not metrics:
        return None
    horizons = metrics.get("horizons", {})
    improvements = []
    for horizon in HORIZONS_MIN:
        summary = horizons.get(str(horizon))
        if not summary:
            return None
        baseline_mae = summary.get("baseline", {}).get("mae")
        model_mae = summary.get("model", {}).get("mae")
        if baseline_mae in (None, 0) or model_mae is None:
            return None
        if isinstance(baseline_mae, str) or isinstance(model_mae, str):
            return None
        improvement = (baseline_mae - model_mae) / baseline_mae
        improvements.append(improvement)
    if not improvements:
        return None
    score = max(0.0, min(1.0, sum(improvements) / len(improvements)))
    return round(score, 3)


def _metrics_ml_ready(metrics: Optional[dict]) -> bool:
    if not metrics:
        return False
    horizons = metrics.get("horizons", {})
    for horizon in HORIZONS_MIN:
        summary = horizons.get(str(horizon))
        if not summary or not summary.get("ml_ready", False):
            return False
    return True


@lru_cache(maxsize=1)
def load_active_bundle() -> Optional[ResidualModelBundle]:
    root = _resolve_model_root()
    model_dir = _find_latest_model_dir(root)
    if not model_dir:
        return None

    metrics = _load_metrics(model_dir / "metrics.json")
    ml_ready = _metrics_ml_ready(metrics)

    models: dict[tuple[int, float], CatBoostRegressor] = {}
    for horizon in HORIZONS_MIN:
        for quantile in QUANTILES:
            model_path = model_dir / f"catboost_residual_{horizon}m_p{int(quantile * 100)}.cbm"
            if not model_path.exists():
                return None
            model = CatBoostRegressor()
            model.load_model(model_path)
            models[(horizon, quantile)] = model

    confidence_score = _compute_confidence(metrics)

    return ResidualModelBundle(
        root=model_dir,
        models=models,
        ml_ready=ml_ready,
        metrics=metrics,
        confidence_score=confidence_score,
    )


def _is_basal_treatment(row: Treatment) -> bool:
    notes_lower = (row.notes or "").lower()
    evt_lower = (getattr(row, "event_type", "") or "").lower()
    return any(key in notes_lower for key in ["basal", "tresiba", "lantus", "toujeo", "levemir"]) or any(
        key in evt_lower for key in ["basal", "temp"]
    )


def _sample_baseline(series: list[ForecastPoint]) -> dict[int, float]:
    points: dict[int, float] = {}
    for horizon in HORIZONS_MIN:
        match = next((p.bg for p in series if p.t_min == horizon), None)
        if match is None and series:
            closest = min(series, key=lambda p: abs(p.t_min - horizon))
            match = closest.bg
        if match is not None:
            points[horizon] = float(match)
    return points


def _basal_active_snapshot(latest_basal: Optional[BasalEntry], now_utc: datetime) -> tuple[float, float]:
    if not latest_basal:
        return 0.0, 0.0
    created_at = latest_basal.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    elapsed_h = max(0.0, (now_utc - created_at).total_seconds() / 3600.0)
    remaining_pct = max(0.0, 1.0 - (elapsed_h / 24.0))
    remaining_u = float(latest_basal.dose_u or 0.0) * remaining_pct
    return remaining_u, elapsed_h * 60.0


def _trend_from_series(series: list[dict]) -> Optional[str]:
    if len(series) < 2:
        return None
    ordered = sorted(series, key=lambda p: p.get("minutes_ago", 0))
    latest = ordered[0]
    oldest = ordered[-1]
    latest_val = latest.get("value")
    oldest_val = oldest.get("value")
    latest_min = latest.get("minutes_ago")
    oldest_min = oldest.get("minutes_ago")
    if None in (latest_val, oldest_val, latest_min, oldest_min):
        return None
    diff_min = abs(oldest_min - latest_min)
    if diff_min <= 0:
        return None
    slope = (latest_val - oldest_val) / diff_min
    if slope >= 3:
        return "DoubleUp"
    if slope >= 2:
        return "SingleUp"
    if slope >= 1:
        return "FortyFiveUp"
    if slope <= -3:
        return "DoubleDown"
    if slope <= -2:
        return "SingleDown"
    if slope <= -1:
        return "FortyFiveDown"
    return "Flat"


async def build_residual_features(
    *,
    now_utc: datetime,
    start_bg: Optional[float],
    recent_bg_series: list[dict],
    treatments: list[Treatment],
    basal_rows: list[BasalEntry],
    ns_config: Optional[NSConfig],
    user_settings: UserSettings,
    store: DataStore,
    baseline_series: list[ForecastPoint],
) -> Optional[dict]:
    if start_bg is None:
        return None
    if not recent_bg_series:
        return None

    baseline_points = _sample_baseline(baseline_series)
    if any(h not in baseline_points for h in HORIZONS_MIN):
        return None

    trend = _trend_from_series(recent_bg_series)
    if trend is None:
        return None

    bg_age_min = recent_bg_series[0].get("minutes_ago")
    if bg_age_min is None:
        return None

    iob_total, _, iob_info, _ = await compute_iob_from_sources(
        now=now_utc,
        settings=user_settings,
        nightscout_client=None,
        data_store=store,
        extra_boluses=None,
    )
    cob_total, cob_info, _ = await compute_cob_from_sources(
        now=now_utc,
        nightscout_client=None,
        data_store=store,
        extra_entries=None,
    )

    if iob_total is None or cob_total is None:
        return None

    bolus_total_3h = 0.0
    bolus_total_6h = 0.0
    carbs_total_3h = 0.0
    carbs_total_6h = 0.0
    basal_total_24h = 0.0
    basal_total_48h = 0.0

    for row in treatments:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        minutes_ago = (now_utc - created_at).total_seconds() / 60.0
        if row.insulin and not _is_basal_treatment(row):
            if minutes_ago <= 180:
                bolus_total_3h += float(row.insulin)
            if minutes_ago <= 360:
                bolus_total_6h += float(row.insulin)
        if row.carbs:
            if minutes_ago <= 180:
                carbs_total_3h += float(row.carbs)
            if minutes_ago <= 360:
                carbs_total_6h += float(row.carbs)
        if row.insulin and _is_basal_treatment(row):
            if minutes_ago <= 1440:
                basal_total_24h += float(row.insulin)
            if minutes_ago <= 2880:
                basal_total_48h += float(row.insulin)

    for row in basal_rows:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        minutes_ago = (now_utc - created_at).total_seconds() / 60.0
        if minutes_ago <= 1440:
            basal_total_24h += float(row.dose_u or 0.0)
        if minutes_ago <= 2880:
            basal_total_48h += float(row.dose_u or 0.0)

    latest_basal = basal_rows[0] if basal_rows else None
    basal_active_u, basal_latest_age_min = _basal_active_snapshot(latest_basal, now_utc)
    basal_latest_u = float(latest_basal.dose_u) if latest_basal else 0.0

    return {
        "bg_mgdl": float(start_bg),
        "bg_age_min": float(bg_age_min),
        "trend": trend,
        "iob_u": float(iob_total),
        "cob_g": float(cob_total),
        "iob_status": iob_info.status,
        "cob_status": cob_info.status,
        "basal_active_u": float(basal_active_u),
        "basal_latest_u": float(basal_latest_u),
        "basal_latest_age_min": float(basal_latest_age_min),
        "basal_total_24h": float(round(basal_total_24h, 2)),
        "basal_total_48h": float(round(basal_total_48h, 2)),
        "bolus_total_3h": float(round(bolus_total_3h, 2)),
        "bolus_total_6h": float(round(bolus_total_6h, 2)),
        "carbs_total_3h": float(round(carbs_total_3h, 2)),
        "carbs_total_6h": float(round(carbs_total_6h, 2)),
        "exercise_minutes_6h": 0.0,
        "exercise_minutes_24h": 0.0,
        "hour_of_day": float(now_utc.hour),
        "day_of_week": float(now_utc.weekday()),
        "source_ns_enabled": float(1.0 if ns_config and ns_config.enabled and ns_config.url else 0.0),
        "source_ns_treatments_count": 0.0,
        "source_db_treatments_count": float(len(treatments)),
        "source_overlap_count": 0.0,
        "source_conflict_count": 0.0,
        "source_consistency_status": "ok",
        "baseline_points": baseline_points,
    }


def _feature_has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


def _build_feature_row(features: dict, horizon_min: int) -> Optional[tuple[list[object], list[int]]]:
    baseline_points = features.get("baseline_points", {})
    baseline_val = baseline_points.get(horizon_min)
    if baseline_val is None:
        return None
    row: list[object] = []
    for name in NUMERIC_FEATURES:
        value = features.get(name)
        if not _feature_has_value(value):
            return None
        row.append(float(value))
    row.append(float(baseline_val))
    for name in CATEGORICAL_FEATURES:
        value = features.get(name)
        if not _feature_has_value(value):
            return None
        row.append(str(value))
    cat_indices = list(range(len(NUMERIC_FEATURES) + 1, len(NUMERIC_FEATURES) + 1 + len(CATEGORICAL_FEATURES)))
    return row, cat_indices


def predict_residuals(
    bundle: ResidualModelBundle,
    features: dict,
) -> Optional[dict[int, dict[float, float]]]:
    residuals: dict[int, dict[float, float]] = {}
    for horizon in HORIZONS_MIN:
        row_data = _build_feature_row(features, horizon)
        if row_data is None:
            return None
        row, cat_indices = row_data
        pool = Pool([row], cat_features=cat_indices)
        horizon_residuals: dict[float, float] = {}
        for quantile in QUANTILES:
            model = bundle.models.get((horizon, quantile))
            if model is None:
                return None
            prediction = float(model.predict(pool)[0])
            horizon_residuals[quantile] = prediction
        residuals[horizon] = horizon_residuals
    return residuals


def _interpolate_residual(residual_points: dict[int, float], t_min: int) -> float:
    points = sorted(residual_points.items())
    if not points:
        return 0.0
    if t_min <= points[0][0]:
        return points[0][1]
    if t_min >= points[-1][0]:
        return points[-1][1]
    for idx in range(len(points) - 1):
        t0, r0 = points[idx]
        t1, r1 = points[idx + 1]
        if t0 <= t_min <= t1:
            if t1 == t0:
                return r0
            ratio = (t_min - t0) / (t1 - t0)
            return r0 + (r1 - r0) * ratio
    return 0.0


def apply_residual_adjustment(
    series: list[ForecastPoint],
    bundle: Optional[ResidualModelBundle],
    features: Optional[dict],
) -> ResidualAdjustmentResult:
    if not bundle or not bundle.ml_ready or not features:
        return ResidualAdjustmentResult(
            applied=False,
            adjusted_series=series,
            ml_prediction=None,
            ml_band=None,
            confidence_score=None,
        )

    residuals = predict_residuals(bundle, features)
    if residuals is None:
        return ResidualAdjustmentResult(
            applied=False,
            adjusted_series=series,
            ml_prediction=None,
            ml_band=None,
            confidence_score=bundle.confidence_score,
        )

    baseline_points = features.get("baseline_points", {})
    if not baseline_points:
        return ResidualAdjustmentResult(
            applied=False,
            adjusted_series=series,
            ml_prediction=None,
            ml_band=None,
            confidence_score=bundle.confidence_score,
        )

    residual_curve = {0: 0.0}
    residual_curve.update({h: residuals[h][0.5] for h in HORIZONS_MIN if h in residuals})
    adjusted_series = [
        ForecastPoint(t_min=point.t_min, bg=round(point.bg + _interpolate_residual(residual_curve, point.t_min), 1))
        for point in series
    ]

    ml_prediction: dict[int, float] = {}
    ml_band: dict[int, dict[str, float]] = {}
    for horizon in HORIZONS_MIN:
        if horizon not in residuals or horizon not in baseline_points:
            continue
        baseline_val = baseline_points[horizon]
        p10 = baseline_val + residuals[horizon][0.1]
        p50 = baseline_val + residuals[horizon][0.5]
        p90 = baseline_val + residuals[horizon][0.9]
        ml_prediction[horizon] = round(p50, 1)
        ml_band[horizon] = {"p10": round(p10, 1), "p90": round(p90, 1)}

    if not ml_prediction:
        return ResidualAdjustmentResult(
            applied=False,
            adjusted_series=series,
            ml_prediction=None,
            ml_band=None,
            confidence_score=bundle.confidence_score,
        )

    return ResidualAdjustmentResult(
        applied=True,
        adjusted_series=adjusted_series,
        ml_prediction=ml_prediction,
        ml_band=ml_band,
        confidence_score=bundle.confidence_score,
    )
