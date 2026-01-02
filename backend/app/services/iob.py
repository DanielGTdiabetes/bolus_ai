from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Literal, Sequence

from sqlalchemy import text
from app.core.db import get_engine, AsyncSession

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
            
    # 1.5 Fetch Local DB (Active Records)
    # Using SQL directly to avoid circular imports or complex deps
    db_boluses = []
    try:
        engine = get_engine()
        if engine:
            async with AsyncSession(engine) as session:
                # Look back dia_hours + buffer
                # Fix TZ mismatch: DB stores naive UTC usually.
                cutoff_aware = now - timedelta(hours=settings.iob.dia_hours + 1)
                cutoff_naive = cutoff_aware.replace(tzinfo=None) # Strip TZ for comparison
                
                # Query treatments table
                query = text("""
                    SELECT created_at, insulin 
                    FROM treatments 
                    WHERE created_at > :cutoff 
                    AND insulin > 0
                """)
                
                result = await session.execute(query, {"cutoff": cutoff_naive})
                rows = result.fetchall()
                
                for r in rows:
                    if r.created_at and r.insulin:
                        ts_iso = r.created_at.replace(tzinfo=timezone.utc).isoformat() if r.created_at.tzinfo is None else r.created_at.isoformat()
                        db_boluses.append({
                            "ts": ts_iso,
                            "units": float(r.insulin)
                        })
    except Exception as e:
        logger.error(f"Failed to fetch DB treatments for IOB: {e}")

    # Merge into extra_boluses if present
    if db_boluses:
        if extra_boluses is None: extra_boluses = []
        extra_boluses.extend(db_boluses)
        if iob_source == "unknown": iob_source = "local_db"
            
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
    
    # 3. Analyze Status & Safety
    # Detect if we are relying on stale local data while NS is down
    has_recent_local = False
    if boluses:
        try:
             # Check if we have any bolus coverage in the last DIA window (e.g. 4h)
             # If all boluses are older than 4h, and NS is down, we have a "Data Gap" risk.
             cutoff_gap = now - timedelta(hours=settings.iob.dia_hours)
             for b in boluses:
                 bts = _safe_parse(b["ts"])
                 if bts and bts > cutoff_gap:
                     has_recent_local = True
                     break
        except Exception:
             pass

    if ns_error:
        if not boluses:
            # Case A: No data at all + NS Error -> Unavailable
            iob_status = "unavailable"
            warning_msg = f"IOB no disponible: {iob_reason} (sin datos locales)."
        elif not has_recent_local:
            # Case B: Old data only + NS Error -> Unavailable (Risk of missing recent NS treatments)
            iob_status = "unavailable"
            warning_msg = f"IOB DESCONOCIDO: {iob_reason}. Sin datos recientes (<{settings.iob.dia_hours}h) en local."
        else:
            # Case C: Recent local data exists + NS Error -> Partial
            iob_status = "partial"
            warning_msg = f"IOB parcial ({iob_reason}). Usando datos locales recientes."
            
    elif not boluses:
        # Success fetching, but nothing found. Value is 0.
        iob_status = "ok"
    else:
        # Success and data found (or local only mode implies ok)
        iob_status = "ok"
        if iob_source == "unknown": iob_source = "local_only"
    
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
            breakdown.append({
                "ts": ts.isoformat(), 
                "units": units, 
                "iob": contribution,
                "duration": duration
            })

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
    extra_entries: list[dict[str, float]] | None = None,
) -> float:
    entries = []
    
    # 1. Fetch Local fallback (always load for merging)
    local_events = []
    try:
        raw_events = data_store.load_events()
        for e in raw_events:
             if e.get("carbs"):
                 local_events.append({"ts": e["ts"], "carbs": float(e["carbs"])})
    except:
        pass

    entries.extend(local_events)

    # 2. Fetch Nightscout
    ns_entries = []
    if nightscout_client:
        try:
            # 6 hours lookback for carbs
            treatments = await nightscout_client.get_recent_treatments(hours=6, limit=1000)
            ns_entries = _carbs_from_treatments(treatments)
        except Exception as exc:
             logger.warning("Nightscout treatments (for COB) unavailable", extra={"error": str(exc)})
    
    # 3. Merge DB (Extra + Query Treatments)
    if extra_entries:
        # DB format usually {"ts": iso, "carbs": val} or similar
        # Ensure format matches
        for e in extra_entries:
            entries.append(e)

    # 3b. Query Local DB Treatments (Active Records)
    # This ensures that even if NS is down, we see the bolus/carbs just entered in the app.
    db_entries = []
    try:
        engine = get_engine()
        if engine:
             async with AsyncSession(engine) as session:
                 # Look back 6 hours (typical COB duration cap)
                 cutoff = now - timedelta(hours=6)
                 cutoff_naive = cutoff.replace(tzinfo=None)
                 
                 query = text("""
                     SELECT created_at, carbs 
                     FROM treatments 
                     WHERE created_at > :cutoff 
                     AND carbs > 0
                 """)
                 
                 result = await session.execute(query, {"cutoff": cutoff_naive})
                 rows = result.fetchall()
                 
                 for r in rows:
                     if r.created_at and r.carbs:
                         ts_iso = r.created_at.replace(tzinfo=timezone.utc).isoformat() if r.created_at.tzinfo is None else r.created_at.isoformat()
                         db_entries.append({
                             "ts": ts_iso,
                             "carbs": float(r.carbs)
                         })
    except Exception as e:
         logger.warning(f"Failed to fetch DB treatments for COB: {e}")
            
    if db_entries:
        entries.extend(db_entries)

    # 4. Merge NS
    if ns_entries:
        for e in ns_entries:
            entries.append(e)
            
    # 5. Deduplicate
    # Reuse simple dedupe logic or implement inline
    # Keys: ts, carbs. Tolerance: 15 min, 1h. Values: exactish.
    unique_entries = []
    
    def _safe_parse(ts_val):
        try:
            val_str = str(ts_val).replace("Z", "+00:00")
            dt = datetime.fromisoformat(val_str)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except:
            return None

    # Sort
    # entries need valid ts
    valid_entries = []
    for e in entries:
        if _safe_parse(e.get("ts")):
            valid_entries.append(e)
            
    valid_entries.sort(key=lambda x: _safe_parse(x["ts"]))
    
    last_e = None
    for e in valid_entries:
        is_dup = False
        e_ts = _safe_parse(e["ts"])
        e_val = float(e.get("carbs", 0))
        # Check if insulin is present? This function uses "extra_entries" (carbs only) + NS (treatments).
        # We should check if 'insulin' key exists and is > 0?
        # compute_cob_from_sources aggregates CARBS. 
        # But if the entry has insulin, usually it's a bolus.
        # "Carb Collision" logic applies primarily to SNACKS (0 insulin).
        # We can simulate this by assuming valid_entries are carb records.
        # But wait, NS treatments return everything.
        e_ins = float(e.get("insulin", 0) or 0)

        if last_e:
            l_ts = _safe_parse(last_e["ts"])
            l_val = float(last_e.get("carbs", 0))
            l_ins = float(last_e.get("insulin", 0) or 0)
            
            dt = abs((e_ts - l_ts).total_seconds())
            
            # 1. Exact Match
            if abs(e_val - l_val) < 1.0 and abs(e_ins - l_ins) < 0.1:
                if dt < 900: is_dup = True
                elif abs(dt - 3600) < 300: is_dup = True
                elif abs(dt - 7200) < 300: is_dup = True
                
            # 2. Carb Collision (Update Logic)
            # If both have NO insulin and are strictly Carb updates
            if not is_dup and e_ins == 0 and l_ins == 0:
                 if dt < 300: # 5 min window
                     # Keep MAX
                     if e_val > l_val:
                         unique_entries.pop()
                         unique_entries.append(e)
                         last_e = e
                         is_dup = True
                     else:
                         is_dup = True
        
        if not is_dup:
            unique_entries.append(e)
            last_e = e

    return compute_cob(now, unique_entries, duration_hours=4.0)
