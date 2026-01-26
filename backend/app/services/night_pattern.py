from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from statistics import median
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import NightPatternConfig
from app.models.forecast import ForecastPoint
from app.models.night_pattern import NightPatternProfile
from app.models.treatment import Treatment
from app.services.forecast_engine import ForecastEngine

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Madrid")


@dataclass
class NightPatternBucketStats:
    median_delta: float
    dispersion: float
    sample_points: int


@dataclass
class NightPatternProfileData:
    buckets: dict[str, NightPatternBucketStats]
    sample_days: int
    sample_points: int
    computed_at: datetime
    bucket_minutes: int
    horizon_minutes: int
    source: str


@dataclass
class NightPatternContext:
    meal_recent: bool
    bolus_recent: bool
    iob_u: Optional[float]
    cob_g: Optional[float]
    trend_slope: Optional[float]
    sustained_rise: bool
    slow_digestion_signal: bool
    last_meal_high_fat_protein: bool
    draft_active: bool = False


def _parse_time_str(value: str) -> time:
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute))


def _window_label(now_local: datetime, cfg: NightPatternConfig) -> Optional[str]:
    if now_local.tzinfo is None:
        now_local = now_local.replace(tzinfo=LOCAL_TZ)
    now_time = now_local.time()
    disable_at = _parse_time_str(cfg.disable_at)
    if now_time >= disable_at:
        return None
    window_a_start = _parse_time_str(cfg.window_a_start)
    window_a_end = _parse_time_str(cfg.window_a_end)
    window_b_start = _parse_time_str(cfg.window_b_start)
    window_b_end = _parse_time_str(cfg.window_b_end)
    if window_a_start <= now_time < window_a_end:
        return "A"
    if window_b_start <= now_time < window_b_end:
        return "B"
    return None


def _bucket_key(dt_local: datetime, bucket_minutes: int) -> str:
    minutes_since_midnight = dt_local.hour * 60 + dt_local.minute
    bucket_start = (minutes_since_midnight // bucket_minutes) * bucket_minutes
    h = bucket_start // 60
    m = bucket_start % 60
    return f"{h:02d}:{m:02d}"


def _is_hypo_treatment(treatment: Treatment) -> bool:
    event_type = (
        getattr(treatment, "event_type", None)
        or getattr(treatment, "eventType", None)
        or ""
    )
    event_type_lower = str(event_type or "").lower()
    notes = (getattr(treatment, "notes", "") or "").lower()
    return any(key in event_type_lower for key in ("hypo", "low", "carb correction")) or any(
        key in notes for key in ("hypo", "low", "glucose tabs", "dextrose")
    )


def _iqr(values: list[float]) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(values)
    q1 = values_sorted[int(0.25 * (len(values_sorted) - 1))]
    q3 = values_sorted[int(0.75 * (len(values_sorted) - 1))]
    return q3 - q1


def _to_local(dt_utc: datetime) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
    return dt_utc.astimezone(LOCAL_TZ)


def _clean_for_training(
    sample_time: datetime,
    treatments: Iterable[Treatment],
    cfg: NightPatternConfig,
) -> bool:
    meal_cutoff = sample_time - timedelta(hours=cfg.meal_lookback_h)
    bolus_cutoff = sample_time - timedelta(hours=cfg.bolus_lookback_h)
    for t in treatments:
        t_time = t.created_at
        if t_time.tzinfo is None:
            t_time = t_time.replace(tzinfo=ZoneInfo("UTC"))
        if t_time >= sample_time:
            continue
        if t_time >= meal_cutoff and (t.carbs or 0) > 0:
            return False
        if t_time >= bolus_cutoff and (t.insulin or 0) > 0:
            return False
        if _is_hypo_treatment(t):
            return False
    return True


def _find_future_value(entries: list[tuple[datetime, float]], idx: int, horizon_min: int, tolerance_min: int) -> Optional[float]:
    start_time, _ = entries[idx]
    target = start_time + timedelta(minutes=horizon_min)
    best = None
    best_diff = None
    for j in range(idx + 1, len(entries)):
        dt, val = entries[j]
        diff = abs((dt - target).total_seconds()) / 60.0
        if diff <= tolerance_min:
            if best_diff is None or diff < best_diff:
                best = val
                best_diff = diff
        if dt > target + timedelta(minutes=tolerance_min):
            break
    return best


def compute_night_pattern_from_cgm(
    entries: list[tuple[datetime, float]],
    treatments: Iterable[Treatment],
    cfg: NightPatternConfig,
    source: str,
) -> Optional[NightPatternProfileData]:
    if not entries:
        return None
    window_end = _parse_time_str(cfg.window_b_end)
    buckets: dict[str, list[float]] = {}
    total_points = 0
    entries_sorted = sorted(entries, key=lambda x: x[0])
    tolerance = max(5, cfg.bucket_minutes)
    for idx, (dt_utc, bg) in enumerate(entries_sorted):
        dt_local = _to_local(dt_utc)
        if dt_local.time() >= window_end:
            continue
        if dt_local.hour >= 4:
            continue
        if not _clean_for_training(dt_utc, treatments, cfg):
            continue
        future_val = _find_future_value(entries_sorted, idx, cfg.horizon_minutes, tolerance)
        if future_val is None:
            continue
        delta = future_val - bg
        bucket = _bucket_key(dt_local, cfg.bucket_minutes)
        buckets.setdefault(bucket, []).append(delta)
        total_points += 1
    if not buckets:
        return None
    bucket_stats: dict[str, NightPatternBucketStats] = {}
    dispersions = []
    for bucket, deltas in buckets.items():
        bucket_median = median(deltas)
        bucket_dispersion = _iqr(deltas)
        bucket_stats[bucket] = NightPatternBucketStats(
            median_delta=float(bucket_median),
            dispersion=float(bucket_dispersion),
            sample_points=len(deltas),
        )
        dispersions.append(bucket_dispersion)
    dispersion_iqr = median(dispersions) if dispersions else 0.0
    return NightPatternProfileData(
        buckets=bucket_stats,
        sample_days=cfg.days,
        sample_points=total_points,
        computed_at=datetime.utcnow(),
        bucket_minutes=cfg.bucket_minutes,
        horizon_minutes=cfg.horizon_minutes,
        source=source,
    )


async def get_or_compute_pattern(
    session: AsyncSession,
    user_id: str,
    cfg: NightPatternConfig,
    source: str,
    cgm_entries: list[tuple[datetime, float]],
    treatments: Iterable[Treatment],
) -> Optional[NightPatternProfileData]:
    stmt = select(NightPatternProfile).where(NightPatternProfile.user_id == user_id)
    res = await session.execute(stmt)
    existing = res.scalars().first()
    now = datetime.utcnow()
    needs_recompute = True
    if existing:
        age = (now - existing.computed_at).total_seconds() / 3600.0
        if (
            age < 24
            and existing.bucket_minutes == cfg.bucket_minutes
            and existing.horizon_minutes == cfg.horizon_minutes
            and existing.sample_days == cfg.days
            and existing.source == source
        ):
            needs_recompute = False
    if not needs_recompute and existing:
        buckets: dict[str, NightPatternBucketStats] = {}
        for key, val in (existing.pattern or {}).items():
            buckets[key] = NightPatternBucketStats(
                median_delta=float(val.get("median_delta", 0.0)),
                dispersion=float(val.get("dispersion", 0.0)),
                sample_points=int(val.get("sample_points", 0)),
            )
        return NightPatternProfileData(
            buckets=buckets,
            sample_days=existing.sample_days,
            sample_points=existing.sample_points,
            computed_at=existing.computed_at,
            bucket_minutes=existing.bucket_minutes,
            horizon_minutes=existing.horizon_minutes,
            source=existing.source,
        )
    computed = compute_night_pattern_from_cgm(cgm_entries, treatments, cfg, source)
    if not computed:
        return None
    payload = {
        key: {
            "median_delta": stats.median_delta,
            "dispersion": stats.dispersion,
            "sample_points": stats.sample_points,
        }
        for key, stats in computed.buckets.items()
    }
    if existing:
        existing.source = source
        existing.bucket_minutes = computed.bucket_minutes
        existing.horizon_minutes = computed.horizon_minutes
        existing.sample_days = computed.sample_days
        existing.sample_points = computed.sample_points
        existing.pattern = payload
        existing.computed_at = computed.computed_at
        existing.dispersion_iqr = median([s.dispersion for s in computed.buckets.values()]) if computed.buckets else 0.0
        session.add(existing)
    else:
        session.add(
            NightPatternProfile(
                user_id=user_id,
                source=source,
                bucket_minutes=computed.bucket_minutes,
                horizon_minutes=computed.horizon_minutes,
                sample_days=computed.sample_days,
                sample_points=computed.sample_points,
                pattern=payload,
                computed_at=computed.computed_at,
                dispersion_iqr=median([s.dispersion for s in computed.buckets.values()]) if computed.buckets else 0.0,
            )
        )
    await session.commit()
    return computed


def evaluate_pattern_application(
    now_local: datetime,
    cfg: NightPatternConfig,
    context: NightPatternContext,
) -> tuple[bool, Optional[str], Optional[str]]:
    if not cfg.enabled:
        return False, "Desactivado por configuración", None
    window = _window_label(now_local, cfg)
    if not window:
        return False, "Fuera de ventana nocturna", None
    if context.meal_recent:
        return False, "Comida reciente dentro del rango", window
    if context.bolus_recent:
        return False, "Bolo reciente dentro del rango", window
    if context.iob_u is None or context.iob_u > cfg.iob_max_u:
        return False, "IOB alto o desconocido", window
    if context.cob_g is None or context.cob_g > 1.0:
        return False, "COB no disponible o elevado", window
    if context.trend_slope is None:
        return False, "Tendencia no disponible", window
    if context.trend_slope > cfg.slope_max_mgdl_per_min:
        return False, "Tendencia al alza", window
    if window == "B":
        if context.slow_digestion_signal or context.sustained_rise or context.last_meal_high_fat_protein:
            return False, "Posible digestión lenta", window
    return True, None, window


def apply_night_pattern_adjustment(
    series: list[ForecastPoint],
    pattern: NightPatternProfileData,
    cfg: NightPatternConfig,
    now_local: datetime,
    context: NightPatternContext,
) -> tuple[list[ForecastPoint], dict, float]:
    applied, reason, window = evaluate_pattern_application(now_local, cfg, context)
    meta = {
        "enabled": cfg.enabled,
        "applied": applied,
        "window": window,
        "reason_not_applied": reason,
        "weight": None,
        "cap_mgdl": cfg.cap_mgdl,
        "sample_days": pattern.sample_days if pattern else None,
        "sample_points": pattern.sample_points if pattern else None,
        "dispersion": None,
        "computed_at": pattern.computed_at if pattern else None,
    }
    if not applied:
        return series, meta, 0.0
    bucket_key = _bucket_key(now_local, cfg.bucket_minutes)
    bucket_stats = pattern.buckets.get(bucket_key)
    if not bucket_stats:
        meta["applied"] = False
        meta["reason_not_applied"] = "Sin datos históricos suficientes"
        return series, meta, 0.0
    weight = cfg.weight_a if window == "A" else cfg.weight_b
    raw_adjust = weight * bucket_stats.median_delta
    if context.trend_slope is not None and context.trend_slope > cfg.slope_max_mgdl_per_min:
        meta["applied"] = False
        meta["reason_not_applied"] = "Tendencia al alza"
        return series, meta, 0.0
    clamped = max(-cfg.cap_mgdl, min(cfg.cap_mgdl, raw_adjust))
    meta["weight"] = weight
    meta["dispersion"] = bucket_stats.dispersion
    adjusted = [
        ForecastPoint(t_min=point.t_min, bg=round(point.bg + clamped, 1))
        for point in series
    ]
    return adjusted, meta, clamped


def trend_slope_from_series(recent_series: Optional[list[dict]]) -> Optional[float]:
    if not recent_series:
        return None
    slope, warnings = ForecastEngine._calculate_momentum(recent_series, lookback_points=5)
    if warnings:
        return None
    return slope


def sustained_rise_detected(recent_series: Optional[list[dict]], rise_threshold: float = 15.0) -> bool:
    if not recent_series:
        return False
    points = []
    for p in recent_series:
        mins = p.get("minutes_ago")
        val = p.get("value")
        if mins is None or val is None:
            continue
        points.append((float(mins), float(val)))
    if len(points) < 2:
        return False
    points.sort(key=lambda x: x[0])
    newest = min(points, key=lambda x: x[0])
    oldest = max(points, key=lambda x: x[0])
    if oldest[0] - newest[0] < 30:
        return False
    rise = newest[1] - oldest[1]
    return rise >= rise_threshold
