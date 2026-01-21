
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from app.models.treatment import Treatment
from app.models.basal import BasalEntry
# Reusing logic from ml_training_pipeline.py as much as possible via copy to decouple

logger = logging.getLogger(__name__)

def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _is_basal_treatment(row: Treatment) -> bool:
    notes_lower = (row.notes or "").lower()
    evt_lower = (row.event_type or "").lower()
    return any(
        key in notes_lower
        for key in ["basal", "tresiba", "lantus", "toujeo", "levemir"]
    ) or any(key in evt_lower for key in ["basal", "temp"])

def _is_exercise_treatment(row: Treatment) -> bool:
    evt_lower = (row.event_type or "").lower()
    notes_lower = (row.notes or "").lower()
    return "exercise" in evt_lower or "ejercicio" in notes_lower

def _basal_active_snapshot(latest_basal: Optional[BasalEntry], now_utc: datetime) -> tuple[float, float]:
    if not latest_basal:
        return 0.0, 0.0
    created_at = _to_utc(latest_basal.created_at)
    elapsed_h = max(0.0, (now_utc - created_at).total_seconds() / 3600.0)
    remaining_pct = max(0.0, 1.0 - (elapsed_h / 24.0)) # Simplified linear 24h model
    remaining_u = float(latest_basal.dose_u or 0.0) * remaining_pct
    return remaining_u, elapsed_h * 60.0

def build_runtime_features(
    user_id: str,
    now_utc: datetime,
    bg_mgdl: Optional[float],
    trend: Optional[str],
    bg_age_min: float,
    iob_u: float,
    cob_g: float,
    to_utc_func,
    basal_rows: List[BasalEntry],
    treatment_rows: List[Treatment],
    # Flags/Status
    iob_status: str = "ok",
    cob_status: str = "ok",
    source_ns_enabled: bool = False,
    ns_treatments_count: int = 0
) -> Dict[str, Any]:
    """
    Constructs the feature vector for ML inference at runtime.
    Matches the schema of ml_training_data_v2.
    """
    
    # Initialize Accumulators
    bolus_total_3h = 0.0
    bolus_total_6h = 0.0
    carbs_total_3h = 0.0
    carbs_total_6h = 0.0
    basal_total_24h = 0.0
    basal_total_48h = 0.0
    exercise_min_6h = 0.0
    exercise_min_24h = 0.0
    
    # Process Treatments (DB Rows)
    # treatment_rows are assumed to be sorted or we verify age
    for row in treatment_rows:
        # created_at might be naive or aware.
        ts = row.created_at
        if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        else: ts = ts.astimezone(timezone.utc)
        
        minutes_ago = (now_utc - ts).total_seconds() / 60.0
        
        if minutes_ago < 0: continue # Future event?
        
        # Bolus / Carbs
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
                
        # Basal in Treatments (rare but possible)
        if row.insulin and _is_basal_treatment(row):
             if minutes_ago <= 1440:
                basal_total_24h += float(row.insulin)
             if minutes_ago <= 2880:
                basal_total_48h += float(row.insulin)
        
        # Exercise (Manual entry)
        if _is_exercise_treatment(row):
            # Assume 30 min per entry if duration missing
            dur = float(row.duration or 30.0)
            if minutes_ago <= 360:
                exercise_min_6h += dur
            if minutes_ago <= 1440:
                exercise_min_24h += dur

    # Process Basal Entries (Official)
    latest_basal = None
    if basal_rows:
        # Assume sorted DESC
        latest_basal = basal_rows[0]
        for row in basal_rows:
            ts = row.created_at
            if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
            minutes_ago = (now_utc - ts).total_seconds() / 60.0
            
            if minutes_ago <= 1440:
                basal_total_24h += float(row.dose_u or 0.0)
            if minutes_ago <= 2880:
                basal_total_48h += float(row.dose_u or 0.0)

    # Basal Snapshots
    basal_active_u, basal_age_min = _basal_active_snapshot(latest_basal, now_utc)
    basal_latest_u = float(latest_basal.dose_u) if latest_basal else 0.0
    
    # Event Counts
    ev_bolus = sum(1 for r in treatment_rows if r.insulin and not _is_basal_treatment(r))
    ev_carb = sum(1 for r in treatment_rows if r.carbs)
    
    return {
        "feature_time": now_utc,
        "user_id": user_id,
        "bg_mgdl": bg_mgdl,
        "trend": trend or "Flat",
        "bg_age_min": bg_age_min,
        "iob_u": iob_u,
        "cob_g": cob_g,
        "iob_status": iob_status,
        "cob_status": cob_status,
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
        "hour_of_day": now_utc.hour,
        "day_of_week": now_utc.weekday(),
        # Meta flags
        "source_ns_enabled": source_ns_enabled,
        "source_ns_treatments_count": ns_treatments_count,
        "source_db_treatments_count": len(treatment_rows),
        "source_overlap_count": 0, # Difficult to calc at runtime cheaply, assume 0
        "source_conflict_count": 0,
        "source_consistency_status": "ok",
        "flag_bg_missing": bg_mgdl is None,
        "flag_bg_stale": bg_age_min > 15,
        "flag_iob_unavailable": iob_status != "ok",
        "flag_cob_unavailable": cob_status != "ok",
        "flag_source_conflict": False
    }
