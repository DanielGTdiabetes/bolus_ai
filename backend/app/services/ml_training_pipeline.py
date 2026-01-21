from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models.basal import BasalEntry
from app.models.forecast import (
    ForecastBasalInjection,
    ForecastEventBolus,
    ForecastEventCarbs,
    ForecastEvents,
    ForecastPoint,
    ForecastSimulateRequest,
    MomentumConfig,
    SimulationParams,
)
from app.models.settings import UserSettings
from app.models.temp_mode import TempModeDB
from app.models.treatment import Treatment
from app.services.forecast_engine import ForecastEngine
from app.services.iob import compute_cob_from_sources, compute_iob_from_sources
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.services.settings_service import get_user_settings_service
from app.services.store import DataStore

logger = logging.getLogger(__name__)

BASELINE_HORIZONS = [30, 60, 120, 240, 360]


@dataclass
class TreatmentSummary:
    rows: list[dict]
    ns_count: int
    db_count: int
    overlap_count: int
    conflict_count: int


def _floor_time(now: datetime, bucket_minutes: int = 5) -> datetime:
    minute = now.minute - (now.minute % bucket_minutes)
    return now.replace(minute=minute, second=0, microsecond=0)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_db_treatment(row: Treatment) -> dict:
    created_at = _to_utc(row.created_at)
    return {
        "id": row.id,
        "nightscout_id": row.nightscout_id,
        "created_at": created_at,
        "insulin": float(row.insulin or 0.0),
        "carbs": float(row.carbs or 0.0),
        "fat": float(row.fat or 0.0),
        "protein": float(row.protein or 0.0),
        "fiber": float(row.fiber or 0.0),
        "notes": row.notes,
        "event_type": row.event_type,
        "source": "db",
    }


def _normalize_ns_treatment(row) -> dict:
    created_at = _to_utc(row.created_at) if row.created_at else None
    return {
        "id": row.id,
        "nightscout_id": row.id,
        "created_at": created_at,
        "insulin": float(row.insulin or 0.0),
        "carbs": float(row.carbs or 0.0),
        "fat": float(row.fat or 0.0),
        "protein": float(row.protein or 0.0),
        "fiber": float(row.fiber or 0.0),
        "notes": row.notes,
        "event_type": row.eventType,
        "source": "nightscout",
    }


def _is_basal_treatment(row: dict) -> bool:
    notes_lower = (row.get("notes") or "").lower()
    evt_lower = (row.get("event_type") or "").lower()
    return any(
        key in notes_lower
        for key in ["basal", "tresiba", "lantus", "toujeo", "levemir"]
    ) or any(key in evt_lower for key in ["basal", "temp"])


def _is_exercise_treatment(row: dict) -> bool:
    evt_lower = (row.get("event_type") or "").lower()
    notes_lower = (row.get("notes") or "").lower()
    return "exercise" in evt_lower or "ejercicio" in notes_lower


def _treatment_matches(a: dict, b: dict, tolerance_min: int = 5) -> bool:
    if a.get("nightscout_id") and a.get("nightscout_id") == b.get("nightscout_id"):
        return True
    if not a.get("created_at") or not b.get("created_at"):
        return False
    diff = abs((a["created_at"] - b["created_at"]).total_seconds()) / 60.0
    if diff > tolerance_min:
        return False
    insulin_match = abs((a.get("insulin") or 0.0) - (b.get("insulin") or 0.0)) <= 0.1
    carbs_match = abs((a.get("carbs") or 0.0) - (b.get("carbs") or 0.0)) <= 1.0
    return insulin_match and carbs_match


def _treatment_conflict(a: dict, b: dict, tolerance_min: int = 5) -> bool:
    if not a.get("created_at") or not b.get("created_at"):
        return False
    diff = abs((a["created_at"] - b["created_at"]).total_seconds()) / 60.0
    if diff > tolerance_min:
        return False
    insulin_match = abs((a.get("insulin") or 0.0) - (b.get("insulin") or 0.0)) <= 0.1
    carbs_match = abs((a.get("carbs") or 0.0) - (b.get("carbs") or 0.0)) <= 1.0
    return not (insulin_match and carbs_match)


def _reconcile_treatments(db_rows: Sequence[Treatment], ns_rows: Sequence) -> TreatmentSummary:
    normalized_db = [_normalize_db_treatment(row) for row in db_rows]
    normalized_ns = [_normalize_ns_treatment(row) for row in ns_rows]
    overlap_count = 0
    conflict_count = 0
    combined = list(normalized_db)

    for ns_row in normalized_ns:
        matched = False
        for db_row in normalized_db:
            if _treatment_matches(ns_row, db_row):
                overlap_count += 1
                matched = True
                break
            if _treatment_conflict(ns_row, db_row):
                conflict_count += 1
                matched = True
                break
        if not matched:
            combined.append(ns_row)

    combined.sort(key=lambda r: r["created_at"] or datetime.min.replace(tzinfo=timezone.utc))
    return TreatmentSummary(
        rows=combined,
        ns_count=len(normalized_ns),
        db_count=len(normalized_db),
        overlap_count=overlap_count,
        conflict_count=conflict_count,
    )


def _recent_bg_series(sgvs: Sequence, now_utc: datetime) -> list[dict]:
    series = []
    for entry in sgvs:
        entry_ts = datetime.fromtimestamp(entry.date / 1000, tz=timezone.utc)
        mins_ago = (now_utc - entry_ts).total_seconds() / 60.0
        if mins_ago < 0:
            mins_ago = 0.0
        if mins_ago <= 60:
            series.append({"minutes_ago": mins_ago, "value": float(entry.sgv)})
    return series


def _resolve_slot_params(user_settings: UserSettings, now_utc: datetime) -> tuple[float, float, int]:
    hour = now_utc.hour
    if user_settings.timezone:
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(user_settings.timezone)
            hour = now_utc.astimezone(tz).hour
        except Exception:
            pass

    s_bk = user_settings.schedule.breakfast_start_hour
    s_ln = user_settings.schedule.lunch_start_hour
    s_dn = user_settings.schedule.dinner_start_hour

    if s_bk <= hour < s_ln:
        return (
            float(user_settings.cr.breakfast),
            float(user_settings.cf.breakfast),
            int(user_settings.absorption.breakfast),
        )
    if s_ln <= hour < s_dn:
        return (
            float(user_settings.cr.lunch),
            float(user_settings.cf.lunch),
            int(user_settings.absorption.lunch),
        )
    return (
        float(user_settings.cr.dinner),
        float(user_settings.cf.dinner),
        int(user_settings.absorption.dinner),
    )


def _sample_forecast(series: list[ForecastPoint]) -> dict[int, float]:
    result: dict[int, float] = {}
    for horizon in BASELINE_HORIZONS:
        match = next((p.bg for p in series if p.t_min == horizon), None)
        if match is None and series:
            closest = min(series, key=lambda p: abs(p.t_min - horizon))
            match = closest.bg
        if match is not None:
            result[horizon] = round(float(match), 1)
    return result


def _basal_active_snapshot(latest_basal: Optional[BasalEntry], now_utc: datetime) -> tuple[float, float]:
    if not latest_basal:
        return 0.0, 0.0
    created_at = _to_utc(latest_basal.created_at)
    elapsed_h = max(0.0, (now_utc - created_at).total_seconds() / 3600.0)
    remaining_pct = max(0.0, 1.0 - (elapsed_h / 24.0))
    remaining_u = float(latest_basal.dose_u or 0.0) * remaining_pct
    return remaining_u, elapsed_h * 60.0


async def build_training_snapshot(
    user_id: str,
    session: AsyncSession,
    now_utc: Optional[datetime] = None,
) -> Optional[dict]:
    now_utc = now_utc or datetime.now(timezone.utc)
    settings = get_settings()
    store = DataStore(Path(settings.data.data_dir))

    settings_data = await get_user_settings_service(user_id, session)
    if not settings_data or not settings_data.get("settings"):
        logger.warning("ML training snapshot skipped: settings missing for user %s", user_id)
        return None
    user_settings = UserSettings.migrate(settings_data["settings"])

    ns_config = await get_ns_config(session, user_id)
    ns_client = None
    bg_val = None
    bg_trend = None
    bg_age_min = None
    recent_series: list[dict] = []
    ns_treatments = []
    if ns_config and ns_config.enabled and ns_config.url:
        ns_client = NightscoutClient(ns_config.url, ns_config.api_secret)
        try:
            latest = await ns_client.get_latest_sgv()
            bg_val = float(latest.sgv)
            bg_trend = latest.direction
            entry_ts = datetime.fromtimestamp(latest.date / 1000, tz=timezone.utc)
            bg_age_min = (now_utc - entry_ts).total_seconds() / 60.0
            history = await ns_client.get_sgv_range(now_utc - timedelta(minutes=45), now_utc, count=20)
            recent_series = _recent_bg_series(history, now_utc)
            ns_treatments = await ns_client.get_recent_treatments(hours=24, limit=200)
        except Exception as exc:
            logger.warning("Nightscout fetch failed for user %s: %s", user_id, exc)
        finally:
            await ns_client.aclose()

    cutoff = now_utc - timedelta(hours=24)
    db_stmt = (
        select(Treatment)
        .where(Treatment.user_id == user_id)
        .where(Treatment.created_at >= cutoff.replace(tzinfo=None))
        .order_by(Treatment.created_at.desc())
    )
    db_rows = (await session.execute(db_stmt)).scalars().all()

    treatment_summary = _reconcile_treatments(db_rows, ns_treatments)

    basal_cutoff = now_utc - timedelta(hours=48)
    basal_stmt = (
        select(BasalEntry)
        .where(BasalEntry.user_id == user_id)
        .where(BasalEntry.created_at >= basal_cutoff.replace(tzinfo=None))
        .order_by(BasalEntry.created_at.desc())
    )
    basal_rows = (await session.execute(basal_stmt)).scalars().all()

    temp_cutoff = now_utc - timedelta(hours=24)
    temp_stmt = (
        select(TempModeDB)
        .where(TempModeDB.user_id == user_id)
        .where(TempModeDB.mode == "exercise")
        .where(TempModeDB.started_at >= temp_cutoff.replace(tzinfo=None))
    )
    temp_rows = (await session.execute(temp_stmt)).scalars().all()

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

    bolus_total_3h = 0.0
    bolus_total_6h = 0.0
    carbs_total_3h = 0.0
    carbs_total_6h = 0.0
    basal_total_24h = 0.0
    basal_total_48h = 0.0
    exercise_min_6h = 0.0
    exercise_min_24h = 0.0
    curr_icr: Optional[float] = None
    curr_isf: Optional[float] = None
    curr_abs: Optional[int] = None

    for row in treatment_summary.rows:
        if not row.get("created_at"):
            continue
        minutes_ago = (now_utc - row["created_at"]).total_seconds() / 60.0
        if row.get("insulin") and not _is_basal_treatment(row):
            if minutes_ago <= 180:
                bolus_total_3h += row["insulin"]
            if minutes_ago <= 360:
                bolus_total_6h += row["insulin"]
        if row.get("carbs"):
            if minutes_ago <= 180:
                carbs_total_3h += row["carbs"]
            if minutes_ago <= 360:
                carbs_total_6h += row["carbs"]
        if row.get("insulin") and _is_basal_treatment(row):
            if minutes_ago <= 1440:
                basal_total_24h += row["insulin"]
            if minutes_ago <= 2880:
                basal_total_48h += row["insulin"]
        if _is_exercise_treatment(row):
            if minutes_ago <= 360:
                exercise_min_6h += 30.0
            if minutes_ago <= 1440:
                exercise_min_24h += 30.0

    for row in basal_rows:
        created_at = _to_utc(row.created_at)
        minutes_ago = (now_utc - created_at).total_seconds() / 60.0
        if minutes_ago <= 1440:
            basal_total_24h += float(row.dose_u or 0.0)
        if minutes_ago <= 2880:
            basal_total_48h += float(row.dose_u or 0.0)

    for row in temp_rows:
        started_at = _to_utc(row.started_at)
        duration_min = max(0.0, (row.expires_at - row.started_at).total_seconds() / 60.0)
        minutes_ago = (now_utc - started_at).total_seconds() / 60.0
        if minutes_ago <= 360:
            exercise_min_6h += duration_min
        if minutes_ago <= 1440:
            exercise_min_24h += duration_min

    latest_basal = basal_rows[0] if basal_rows else None
    basal_active_u, basal_age_min = _basal_active_snapshot(latest_basal, now_utc)
    basal_latest_u = float(latest_basal.dose_u) if latest_basal else 0.0

    forecast_points: dict[int, float] = {}
    if bg_val is not None:
        curr_icr, curr_isf, curr_abs = _resolve_slot_params(user_settings, now_utc)
        events = ForecastEvents()
        horizon_cutoff = now_utc - timedelta(hours=12)

        for row in treatment_summary.rows:
            if not row.get("created_at") or row["created_at"] < horizon_cutoff:
                continue
            diff_min = (now_utc - row["created_at"]).total_seconds() / 60.0
            offset = -1 * diff_min
            if row.get("insulin") and not _is_basal_treatment(row):
                events.boluses.append(
                    ForecastEventBolus(
                        time_offset_min=int(offset),
                        units=row["insulin"],
                        duration_minutes=0.0,
                    )
                )
            if row.get("carbs"):
                events.carbs.append(
                    ForecastEventCarbs(
                        time_offset_min=int(offset),
                        grams=row["carbs"],
                        icr=curr_icr,
                        absorption_minutes=curr_abs,
                        fat_g=row.get("fat", 0.0),
                        protein_g=row.get("protein", 0.0),
                        fiber_g=row.get("fiber", 0.0),
                    )
                )

        basal_injections = []
        for row in basal_rows:
            created_at = _to_utc(row.created_at)
            diff_min = (now_utc - created_at).total_seconds() / 60.0
            basal_injections.append(
                ForecastBasalInjection(
                    time_offset_min=int(-1 * diff_min),
                    units=float(row.dose_u or 0.0),
                    duration_minutes=int((row.effective_hours or 24) * 60),
                    type=row.basal_type or "glargine",
                )
            )
        events.basal_injections = basal_injections

        params = SimulationParams(
            isf=curr_isf,
            icr=curr_icr,
            dia_minutes=int(user_settings.iob.dia_hours * 60),
            carb_absorption_minutes=curr_abs,
            insulin_peak_minutes=user_settings.iob.peak_minutes,
            insulin_model=user_settings.iob.curve,
            basal_daily_units=basal_latest_u,
            target_bg=float(user_settings.targets.mid),
        )
        req = ForecastSimulateRequest(
            start_bg=bg_val,
            units="mgdl",
            horizon_minutes=360,
            step_minutes=5,
            momentum=MomentumConfig(enabled=True, lookback_points=3),
            params=params,
            events=events,
            recent_bg_series=recent_series or None,
        )
        response = ForecastEngine.calculate_forecast(req)
        forecast_points = _sample_forecast(response.series)

    flag_bg_missing = bg_val is None
    flag_bg_stale = bool(bg_age_min is not None and bg_age_min > 15)
    flag_iob_unavailable = iob_info.status in ["unavailable", "stale"]
    flag_cob_unavailable = cob_info.status in ["unavailable", "stale"]
    flag_source_conflict = treatment_summary.conflict_count > 0

    active_params = {
        "icr": curr_icr if bg_val is not None else None,
        "isf": curr_isf if bg_val is not None else None,
        "target_bg": float(user_settings.targets.mid),
        "dia_hours": float(user_settings.iob.dia_hours),
        "insulin_curve": user_settings.iob.curve,
        "insulin_peak_minutes": int(user_settings.iob.peak_minutes),
        "absorption_minutes": curr_abs if bg_val is not None else None,
    }

    event_counts = {
        "bolus_events": sum(1 for row in treatment_summary.rows if row.get("insulin") and not _is_basal_treatment(row)),
        "carb_events": sum(1 for row in treatment_summary.rows if row.get("carbs")),
        "basal_events": sum(1 for row in treatment_summary.rows if row.get("insulin") and _is_basal_treatment(row)),
        "exercise_events": sum(1 for row in treatment_summary.rows if _is_exercise_treatment(row)),
    }

    return {
        "feature_time": _floor_time(now_utc),
        "user_id": user_id,
        "bg_mgdl": bg_val,
        "trend": bg_trend,
        "bg_age_min": bg_age_min,
        "iob_u": iob_total,
        "cob_g": cob_total,
        "iob_status": iob_info.status,
        "cob_status": cob_info.status,
        "basal_active_u": basal_active_u,
        "basal_latest_u": basal_latest_u,
        "basal_latest_age_min": basal_age_min,
        "basal_total_24h": round(basal_total_24h, 2),
        "basal_total_48h": round(basal_total_48h, 2),
        "bolus_total_3h": round(bolus_total_3h, 2),
        "bolus_total_6h": round(bolus_total_6h, 2),
        "carbs_total_3h": round(carbs_total_3h, 2),
        "carbs_total_6h": round(carbs_total_6h, 2),
        "exercise_minutes_6h": round(exercise_min_6h, 1),
        "exercise_minutes_24h": round(exercise_min_24h, 1),
        "baseline_bg_30m": forecast_points.get(30),
        "baseline_bg_60m": forecast_points.get(60),
        "baseline_bg_120m": forecast_points.get(120),
        "baseline_bg_240m": forecast_points.get(240),
        "baseline_bg_360m": forecast_points.get(360),
        "active_params": json.dumps(active_params, default=str),
        "event_counts": json.dumps(event_counts, default=str),
        "source_ns_enabled": bool(ns_config and ns_config.enabled and ns_config.url),
        "source_ns_treatments_count": treatment_summary.ns_count,
        "source_db_treatments_count": treatment_summary.db_count,
        "source_overlap_count": treatment_summary.overlap_count,
        "source_conflict_count": treatment_summary.conflict_count,
        "source_consistency_status": "ok" if treatment_summary.conflict_count == 0 else "mismatch",
        "flag_bg_missing": flag_bg_missing,
        "flag_bg_stale": flag_bg_stale,
        "flag_iob_unavailable": flag_iob_unavailable,
        "flag_cob_unavailable": flag_cob_unavailable,
        "flag_source_conflict": flag_source_conflict,
    }


async def persist_training_snapshot(session: AsyncSession, snapshot: dict) -> None:
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ml_training_data_v2 (
                feature_time TIMESTAMP NOT NULL,
                user_id VARCHAR NOT NULL,
                bg_mgdl FLOAT,
                trend VARCHAR,
                bg_age_min FLOAT,
                iob_u FLOAT,
                cob_g FLOAT,
                iob_status VARCHAR,
                cob_status VARCHAR,
                basal_active_u FLOAT,
                basal_latest_u FLOAT,
                basal_latest_age_min FLOAT,
                basal_total_24h FLOAT,
                basal_total_48h FLOAT,
                bolus_total_3h FLOAT,
                bolus_total_6h FLOAT,
                carbs_total_3h FLOAT,
                carbs_total_6h FLOAT,
                exercise_minutes_6h FLOAT,
                exercise_minutes_24h FLOAT,
                baseline_bg_30m FLOAT,
                baseline_bg_60m FLOAT,
                baseline_bg_120m FLOAT,
                baseline_bg_240m FLOAT,
                baseline_bg_360m FLOAT,
                active_params TEXT,
                event_counts TEXT,
                source_ns_enabled BOOLEAN,
                source_ns_treatments_count INTEGER,
                source_db_treatments_count INTEGER,
                source_overlap_count INTEGER,
                source_conflict_count INTEGER,
                source_consistency_status VARCHAR,
                flag_bg_missing BOOLEAN,
                flag_bg_stale BOOLEAN,
                flag_iob_unavailable BOOLEAN,
                flag_cob_unavailable BOOLEAN,
                flag_source_conflict BOOLEAN,
                PRIMARY KEY (feature_time, user_id)
            )
            """
        )
    )
    insert_sql = text(
        """
        INSERT INTO ml_training_data_v2 (
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
            active_params,
            event_counts,
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
        )
        VALUES (
            :feature_time,
            :user_id,
            :bg_mgdl,
            :trend,
            :bg_age_min,
            :iob_u,
            :cob_g,
            :iob_status,
            :cob_status,
            :basal_active_u,
            :basal_latest_u,
            :basal_latest_age_min,
            :basal_total_24h,
            :basal_total_48h,
            :bolus_total_3h,
            :bolus_total_6h,
            :carbs_total_3h,
            :carbs_total_6h,
            :exercise_minutes_6h,
            :exercise_minutes_24h,
            :baseline_bg_30m,
            :baseline_bg_60m,
            :baseline_bg_120m,
            :baseline_bg_240m,
            :baseline_bg_360m,
            :active_params,
            :event_counts,
            :source_ns_enabled,
            :source_ns_treatments_count,
            :source_db_treatments_count,
            :source_overlap_count,
            :source_conflict_count,
            :source_consistency_status,
            :flag_bg_missing,
            :flag_bg_stale,
            :flag_iob_unavailable,
            :flag_cob_unavailable,
            :flag_source_conflict
        )
        ON CONFLICT (feature_time, user_id) DO NOTHING
        """
    )
    await session.execute(insert_sql, snapshot)
    await session.commit()


async def collect_and_persist_training_snapshot(
    user_id: str,
    session: AsyncSession,
    now_utc: Optional[datetime] = None,
) -> Optional[dict]:
    snapshot = await build_training_snapshot(user_id, session, now_utc=now_utc)
    if not snapshot:
        return None
    await persist_training_snapshot(session, snapshot)
    return snapshot
