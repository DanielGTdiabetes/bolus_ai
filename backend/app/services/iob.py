from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Sequence

from app.models.settings import UserSettings
from app.services.store import DataStore

logger = logging.getLogger(__name__)


@dataclass
class InsulinActionProfile:
    dia_hours: float
    curve: Literal["walsh", "bilinear"]
    peak_minutes: int = 75


def _clamp(value: float, min_value: float = 0.0, max_value: float | None = None) -> float:
    if max_value is not None:
        value = min(value, max_value)
    return max(value, min_value)


def _parse_timestamp(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def insulin_activity_fraction(t_minutes: float, profile: InsulinActionProfile) -> float:
    dia_minutes = profile.dia_hours * 60
    if t_minutes <= 0:
        return 1.0
    if t_minutes >= dia_minutes:
        return 0.0

    if profile.curve == "bilinear":
        peak = max(1, profile.peak_minutes)
        if peak >= dia_minutes:
            peak = dia_minutes / 2
        # Linear decay to mid-point at the peak, then faster decay to DIA
        slope1 = 0.5 / peak
        slope2 = 0.5 / (dia_minutes - peak)
        if t_minutes <= peak:
            remaining = 1.0 - slope1 * t_minutes
        else:
            remaining = 0.5 - slope2 * (t_minutes - peak)
        return _clamp(remaining)

    # Smoothstep curve used as a stable approximation of the Walsh IOB model.
    # It provides a smooth, monotonic decay from 1.0 at t=0 to 0.0 at DIA with
    # zero slope at both ends, avoiding oscillations without external libs.
    x = t_minutes / dia_minutes
    smooth = 1 - (3 * x**2 - 2 * x**3)
    return _clamp(smooth)


def compute_iob(now: datetime, boluses: Sequence[dict[str, float]], profile: InsulinActionProfile) -> float:
    total = 0.0
    for bolus in boluses:
        ts_raw = bolus.get("ts")
        units = float(bolus.get("units", 0))
        if not ts_raw or units <= 0:
            continue
        ts = _parse_timestamp(str(ts_raw))
        elapsed = (now - ts).total_seconds() / 60
        fraction = insulin_activity_fraction(elapsed, profile)
        total += units * fraction
    return max(total, 0.0)


def _boluses_from_events(events: list[dict]) -> list[dict[str, float]]:
    boluses: list[dict[str, float]] = []
    for event in events:
        if event.get("type") != "bolus":
            continue
        units = float(event.get("units", 0))
        ts = event.get("ts")
        if units > 0 and ts:
            boluses.append({"ts": ts, "units": units})
    return boluses


def _boluses_from_treatments(treatments) -> list[dict[str, float]]:
    boluses: list[dict[str, float]] = []
    for treatment in treatments:
        units = getattr(treatment, "insulin", None)
        ts = getattr(treatment, "created_at", None)
        if units is None or ts is None:
            continue
        boluses.append({"ts": ts.isoformat(), "units": float(units)})
    return boluses


from app.models.iob import IOBInfo, IOBStatus

async def compute_iob_from_sources(
    now: datetime,
    settings: UserSettings,
    nightscout_client,
    data_store: DataStore,
) -> tuple[float, list[dict[str, float]], IOBInfo, Optional[str]]:
    """
    Computes IOB with detailed status reporting.
    Returns: (internal_iob, breakdown, iob_info, warning_msg)
    """
    profile = InsulinActionProfile(
        dia_hours=settings.iob.dia_hours,
        curve=settings.iob.curve,
        peak_minutes=settings.iob.peak_minutes,
    )

    boluses: list[dict[str, float]] = []
    breakdown: list[dict[str, float]] = []
    
    iob_status: IOBStatus = "unavailable"
    iob_reason: Optional[str] = None
    iob_source: str = "unknown"
    warning_msg: Optional[str] = None
    
    ns_error = None
    fetched_count = 0

    # 1. Fetch from Nightscout
    ns_boluses = []
    if nightscout_client:
        try:
            iob_source = "nightscout+local"
            hours = max(1, math.ceil(settings.iob.dia_hours))
            treatments = await nightscout_client.get_recent_treatments(hours=hours, limit=1000)
            ns_boluses = _boluses_from_treatments(treatments)
            iob_status = "ok"
        except Exception as exc:
            ns_error = str(exc)
            if "Unauthorized" in ns_error:
                iob_reason = "Nightscout no autorizado"
            elif "Timeout" in ns_error:
                iob_reason = "Nightscout timeout"
            else:
                 iob_reason = f"Error Nightscout: {ns_error}"
            
            logger.warning("Nightscout treatments unavailable", extra={"error": ns_error})
            # Fallback to local only for source label if NS failed completely
            iob_source = "local_db_fallback"
            
    # 2. Fetch from Local Store (Always, to catch recent pending uploads)
    local_boluses = []
    local_events = data_store.load_events()
    if local_events:
        local_boluses = _boluses_from_events(local_events)
    
    # 3. Merge and Deduplicate
    # We prioritize Local for recent events (as they are "truth" for the device)
    # but we need NS for older history if local is empty (e.g. new device).
    # Dedupe Key: (timestamp_iso, units)
    
    unique_map = {}
    
    # Add NS first
    for b in ns_boluses:
        key = (b["ts"], float(b["units"]))
        unique_map[key] = b
        
    # Add Local (overwriting if exact match, or adding if new)
    # Note: Timestamps must match exactly. If NS modifies timestamp slightly, we might double count.
    # To be safe, we can check for "close" timestamps (within 60s) with same units? 
    # For now, strict match is safer against deleting distinct boluses.
    for b in local_boluses:
        key = (b["ts"], float(b["units"]))
        # If we want to prefer local (e.g. it has more metadata?), we overwrite.
        # But for IOB, unit/time is all that matters.
        unique_map[key] = b
        
    boluses = list(unique_map.values())
    
    if not boluses and ns_error:
        iob_status = "unavailable"
        warning_msg = f"IOB no disponible: {iob_reason}."
    elif ns_error and boluses:
        iob_status = "partial"
        warning_msg = f"IOB parcial (Nightscout falló). Usando datos locales."
    
    # 3. Compute
    total = 0.0
    for bolus in boluses:
        ts_raw = bolus.get("ts")
        units = float(bolus.get("units", 0))
        if not ts_raw:
            continue
        ts = _parse_timestamp(str(ts_raw))
        elapsed = (now - ts).total_seconds() / 60
        fraction = insulin_activity_fraction(elapsed, profile)
        contribution = max(units * fraction, 0.0)
        total += contribution
        breakdown.append({"ts": ts.isoformat(), "units": units, "iob": contribution})

    breakdown.sort(key=lambda item: item["ts"], reverse=True)
    final_iob = max(total, 0.0)
    
    # 4. Construct Info
    # If status is unavailable, we might still have computed 0.0, but we flag it as not trusted.
    # The caller (calculate_bolus) should decide whether to use 0.0 or prompt user.
    # Proposal says: "Unavailable -> iob_u_internal=0.0, iob_info.iob_u=None"
    
    public_iob = final_iob
    if iob_status == "unavailable":
        public_iob = None
        final_iob = 0.0 # Safety for internal calculation (do not subtract anything)
        
    info = IOBInfo(
        iob_u=public_iob,
        status=iob_status,
        reason=iob_reason,
        source=iob_source,
        fetched_at=now
    )
    
    return final_iob, breakdown, info, warning_msg


def compute_cob(now: datetime, carb_entries: Sequence[dict[str, float]], duration_hours: float = 4.0) -> float:
    total = 0.0
    duration_min = duration_hours * 60
    for entry in carb_entries:
        ts_raw = entry.get("ts")
        grams = float(entry.get("carbs", 0))
        if not ts_raw or grams <= 0:
            continue
        ts = _parse_timestamp(str(ts_raw))
        elapsed = (now - ts).total_seconds() / 60
        if elapsed < 0: elapsed = 0
        
        if elapsed >= duration_min:
            fraction = 0.0
        else:
            fraction = 1.0 - (elapsed / duration_min)
        
        total += grams * fraction
    return max(total, 0.0)

def _carbs_from_treatments(treatments) -> list[dict[str, float]]:
    entries: list[dict[str, float]] = []
    for treatment in treatments:
        carbs = getattr(treatment, "carbs", None)
        ts = getattr(treatment, "created_at", None)
        if carbs is None or ts is None:
            continue
        entries.append({"ts": ts.isoformat(), "carbs": float(carbs)})
    return entries

async def compute_cob_from_sources(
    now: datetime,
    nightscout_client,
    data_store: DataStore,
) -> float:
    entries = []
    if nightscout_client:
        try:
            # 6 hours lookback for carbs
            treatments = await nightscout_client.get_recent_treatments(hours=6, limit=1000)
            entries.extend(_carbs_from_treatments(treatments))
        except Exception as exc:
             logger.warning("Nightscout treatments (for COB) unavailable", extra={"error": str(exc)})
    
    # Also Check Local? 
    # Usually we rely on NS if enabled, but local if not.
    if not entries:
        # Minimal local fallback
        events = data_store.load_events()
        for e in events:
             if e.get("carbs"):
                 entries.append({"ts": e["ts"], "carbs": float(e["carbs"])})

    return compute_cob(now, entries, duration_hours=4.0)
