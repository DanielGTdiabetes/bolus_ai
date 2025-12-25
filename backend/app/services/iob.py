from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Sequence

from app.models.settings import UserSettings
from app.services.store import DataStore
from app.services.math.curves import InsulinCurves

logger = logging.getLogger(__name__)


@dataclass
class InsulinActionProfile:
    dia_hours: float
    curve: Literal["walsh", "bilinear", "fiasp", "novorapid", "linear"]
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
    
    # Use unified curve logic for consistent IOB
    return InsulinCurves.get_iob(
        t_minutes, 
        dia_minutes, 
        profile.peak_minutes, 
        str(profile.curve)
    )


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
        boluses.append({
            "ts": ts.isoformat(), 
            "units": float(units),
            "duration": float(getattr(treatment, "duration", 0) or 0)
        })
    return boluses


from app.models.iob import IOBInfo, IOBStatus

async def compute_iob_from_sources(
    now: datetime,
    settings: UserSettings,
    nightscout_client,
    data_store: DataStore,
    extra_boluses: list[dict[str, float]] | None = None,
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
    try:
        local_events = data_store.load_events()
        if local_events:
            local_boluses = _boluses_from_events(local_events)
    except Exception as e:
        logger.error(f"Failed to load local events: {e}")
    
    # 3. Merge Local + Extra (DB) + Nightscout
    unique_boluses = []
    
    # Start with Local as base (most trusted for recent)
    unique_boluses.extend(local_boluses)
    
    def _safe_parse(ts_val):
        try:
            return _parse_timestamp(str(ts_val))
        except Exception:
            logger.warning(f"Failed to parse timestamp: {ts_val}", exc_info=True)
            return None

    def _is_duplicate(candidate: dict, existing_list: list[dict]) -> bool:
        c_ts = _safe_parse(candidate["ts"])
        if not c_ts: return True # Skip invalid candidate
        
        c_units = float(candidate["units"])
        
        for ex in existing_list:
            ex_ts = _safe_parse(ex["ts"])
            if not ex_ts: continue 
            
            ex_units = float(ex["units"])
            
            # Check units (exact or very close)
            if abs(c_units - ex_units) > 0.01:
                continue
                
            # Check time (within 15 minutes tolerance for clock skew/format diffs)
            diff_seconds = abs((c_ts - ex_ts).total_seconds())
            
            # 1. Standard close proximity (15 min)
            if diff_seconds < 900: 
                return True
                
            # 2. Timezone Glitch Guard
            # Often local time is parsed as UTC, creating 1h (CET) or 2h (CEST) offsets.
            # If units are identical and time difference is exactly ~1h or ~2h, treat as dupe.
            # Tolerance 5 min around the hour mark.
            
            # Check 1 hour (3600s)
            if abs(diff_seconds - 3600) < 300:
                return True
                
            # Check 2 hours (7200s)
            if abs(diff_seconds - 7200) < 300:
                return True
                
        return False
        
    # Merge DB into Unique
    if extra_boluses:
        for b in extra_boluses:
            if not _is_duplicate(b, unique_boluses):
                unique_boluses.append(b)

    # Merge NS into Unique
    for b in ns_boluses:
        if not _is_duplicate(b, unique_boluses):
            unique_boluses.append(b)
            
    boluses = unique_boluses
    
    if not boluses and ns_error:
        # If we have NO boluses and NS failed, we flag unavailable.
        # If we have local/db boluses, we use partial.
        iob_status = "unavailable"
        warning_msg = f"IOB no disponible: {iob_reason}."
    elif ns_error and boluses:
        iob_status = "partial"
        warning_msg = f"IOB parcial (Nightscout falló). Usando datos locales/DB."
    elif not ns_error and not boluses:
        # Success fetching, but nothing found. Value is 0.
        iob_status = "ok"
    elif iob_status == "unavailable" and not ns_error and boluses:
        # Nightscout disconnected/disabled but we have local data. IOB is valid based on local data.
        iob_status = "ok"
        iob_source = "local_only"
    
    # 3. Compute
    total = 0.0
    for bolus in boluses:
        ts_raw = bolus.get("ts")
        units = float(bolus.get("units", 0))
        ts = _safe_parse(ts_raw)
        if not ts or units <= 0:
            continue
        
        # Square Wave Support
        duration = float(bolus.get("duration", 0.0))
        
        elapsed = (now - ts).total_seconds() / 60
        
        contribution = 0.0
        
        if duration > 10:
             # Square wave simulation: split into chunks
             # Same logic as forecast engine generally, but simpler integration
             # Fraction of insulin "delivered" so far? No, IOB is "remaining action".
             # For a square wave, we have insulin NOT YET DELIVERED + insulin delivered but interacting.
             
             # Actually, standard IOB calculation for Extended Bolus is tricky.
             # Loop/OpenAPS usually model it as:
             # IOB = (Scheduled - Delivered) + Decay(Delivered)
             # If "duration" is passed, we assume valid delivery over time.
             
             # Let's simplify: discretized chunks.
             chunk_step = 5.0
             n_chunks = math.ceil(duration / chunk_step)
             u_per_chunk = units / n_chunks
             
             for k in range(n_chunks):
                 t_chunk_offset = k * chunk_step
                 
                 # If chunk is in future (not delivered yet)
                 # It counts as IOB in the sense of "Active" or "On Board" (Total Future Insulin)?
                 # "Insulin On Board" usually implies "Active in body".
                 # Undelivered insulin is technically "On Board" in many contexts (pump IOB includes it).
                 # Let's count it.
                 
                 t_since_chunk = elapsed - t_chunk_offset
                 
                 if t_since_chunk < 0:
                     # Future delivery. It is fully "on board" (pending).
                     # Counts as 1.0 (100% remaining).
                     chunk_contribution = u_per_chunk
                 else:
                     # Delivered, decaying
                     f = insulin_activity_fraction(t_since_chunk, profile)
                     chunk_contribution = u_per_chunk * f
                 
                 contribution += chunk_contribution
        else:
             fraction = insulin_activity_fraction(elapsed, profile)
             contribution = max(units * fraction, 0.0)
             
        total += contribution
        if contribution > 0.01: # Only include significant in breakdown
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
