from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Literal, Sequence, Optional

from sqlalchemy import text
from app.core.db import get_engine, AsyncSession

from app.models.settings import UserSettings
from app.services.store import DataStore
from app.services.math.curves import InsulinCurves, CarbCurves

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


from app.models.iob import IOBInfo, IOBStatus, SourceStatus, COBInfo, COBStatus

async def compute_iob_from_sources(
    now: datetime,
    settings: UserSettings,
    nightscout_client,
    data_store: DataStore,
    extra_boluses: list[dict[str, float]] | None = None,
    user_id: Optional[str] = None,
) -> tuple[Optional[float], list[dict[str, float]], IOBInfo, Optional[str]]:
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
    treatments_status = SourceStatus(source="nightscout", status="unknown")
    cache_iob: Optional[float] = None
    cache_ts: Optional[datetime] = None
    
    try:
        cache_raw = data_store.read_json("iob_cache.json", {"iob_u": None, "fetched_at": None})
        if cache_raw.get("iob_u") is not None and cache_raw.get("fetched_at"):
            cache_iob = float(cache_raw["iob_u"])
            cache_ts = datetime.fromisoformat(str(cache_raw["fetched_at"]))
    except Exception:
        cache_iob = None
        cache_ts = None
    
    ns_error = None

    # 1. Skip Fetch from Nightscout (Write-Only Mode for Treatments)
    # User requested to NEVER read treatments from NS, only write.
    # We rely exclusively on Local DB.
    iob_source = "local_only"
    treatments_status.status = "ok" # Local is the source of truth
    treatments_status.fetched_at = now
    
    # We set ns_boluses to empty
    ns_boluses = []
            
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
                params = {"cutoff": cutoff_naive}
                if user_id:
                    query = text("""
                        SELECT created_at, insulin, event_type, notes
                        FROM treatments 
                        WHERE created_at > :cutoff 
                        AND insulin > 0
                        AND user_id = :user_id
                    """)
                    params["user_id"] = user_id
                else:
                    query = text("""
                        SELECT created_at, insulin, event_type, notes
                        FROM treatments 
                        WHERE created_at > :cutoff 
                        AND insulin > 0
                    """)
                
                result = await session.execute(query, params)
                rows = result.fetchall()
                
                for r in rows:
                    if r.created_at and r.insulin:
                        # Filter out Basal
                        evt_type = (getattr(r, "event_type", "") or "").lower()
                        notes_val = (getattr(r, "notes", "") or "").lower()
                        
                        # Exclude obvious basal entries
                        if "basal" in evt_type or "basal" in notes_val or "lenta" in notes_val:
                            continue

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
            if user_id:
                local_events = [e for e in local_events if e.get("user_id") == user_id]
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
            # Case A: No data at all + NS Error -> Unavailable unless cache exists
            if cache_iob is not None:
                iob_status = "stale"
                warning_msg = f"IOB desactualizado: {iob_reason} (usando último valor cacheado)."
                treatments_status.status = "stale"
            else:
                iob_status = "unavailable"
                warning_msg = f"IOB no disponible: {iob_reason} (sin datos locales)."
        elif not has_recent_local:
            # Case B: Old data only + NS Error ->
            # Relaxed Logic: If we successfully queried the local DB (implied by execution reaching here without DB error),
            # and found nothing recent, it likely means IOB is 0.
            # We should only error if we specifically suspect a data gap (e.g. fresh install with no history).
            # But generally, silence is 0.
            
            # Use Local Fallback
            iob_status = "partial" # Mark as partial to indicate NS is missing, but value is valid (0)
            warning_msg = f"Nightscout caído ({iob_reason}). Asumiendo 0 IOB por falta de datos recientes."
            treatments_status.status = "error"
            
        else:
            # Case C: Recent local data exists + NS Error -> Partial
            iob_status = "partial"
            warning_msg = f"Nightscout caído ({iob_reason}). Usando datos locales recientes."
            treatments_status.status = "error"
            
    elif not boluses:
        # Success fetching (Local), but nothing found. Value is 0.
        iob_status = "ok"
        treatments_status.status = "ok"
    else:
        # Success and data found
        iob_status = "ok"
        treatments_status.status = "ok"
    
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
    public_iob: Optional[float] = final_iob
    last_known = cache_iob
    last_ts = cache_ts
    if iob_status in ["unavailable", "stale"]:
        public_iob = None
        final_iob = None
        if last_known is not None:
            # Keep cached last known for transparency
            if last_ts is None:
                last_ts = now
            treatments_status.status = "stale"
    else:
        last_known = public_iob
        last_ts = now
    
    info = IOBInfo(
        iob_u=public_iob,
        status=iob_status,
        reason=iob_reason,
        source=iob_source,
        fetched_at=now,
        last_known_iob=last_known,
        last_updated_at=last_ts,
        treatments_source_status=treatments_status,
        assumptions=[]
    )
    
    try:
        data_store.write_json("iob_cache.json", {
            "iob_u": last_known,
            "fetched_at": last_ts.isoformat() if last_ts else None,
            "status": iob_status
        })
    except Exception:
        pass
    
    return final_iob, breakdown, info, warning_msg


def compute_cob_linear(now: datetime, carb_entries: Sequence[dict[str, float]], duration_hours: float = 4.0) -> float:
    total = 0.0
    duration_min = duration_hours * 60
    for entry in carb_entries:
        ts_raw = entry.get("ts")
        grams = float(entry.get("carbs", 0))
        if not ts_raw or grams <= 0:
            continue
        ts = _parse_timestamp(str(ts_raw))
        elapsed = (now - ts).total_seconds() / 60
        if elapsed < 0:
            elapsed = 0
        
        if elapsed >= duration_min:
            fraction = 0.0
        else:
            fraction = 1.0 - (elapsed / duration_min)
        
        total += grams * fraction
    return max(total, 0.0)


def _carbcurves_remaining(now: datetime, entry: dict) -> float:
    ts_raw = entry.get("ts")
    grams = float(entry.get("carbs", 0) or 0)
    if not ts_raw or grams <= 0:
        return 0.0
    ts = _parse_timestamp(str(ts_raw))
    elapsed = max(0.0, (now - ts).total_seconds() / 60.0)

    fiber = float(entry.get("fiber") or entry.get("fiber_g") or 0.0)
    fat = float(entry.get("fat") or 0.0)
    protein = float(entry.get("protein") or 0.0)

    params = CarbCurves.get_biexponential_params(grams, fiber, fat, protein)
    duration_cap = max(120.0, min(360.0, (params.get("t_max_l", 120.0) * 3.0)))
    step = 5.0

    absorbed_area = 0.0
    total_area = 0.0
    t = 0.0
    while t < duration_cap:
        next_t = min(duration_cap, t + step)
        rate = CarbCurves.biexponential_absorption(t, params)
        dt = next_t - t
        total_area += rate * dt
        if elapsed > t:
            effective_dt = min(dt, max(0.0, elapsed - t))
            absorbed_area += rate * effective_dt
        t = next_t

    if total_area <= 0:
        return grams

    absorbed_fraction = min(1.0, absorbed_area / total_area)
    remaining_fraction = max(0.0, 1.0 - absorbed_fraction)
    return grams * remaining_fraction

def _carbs_from_treatments(treatments) -> list[dict[str, float]]:
    entries: list[dict[str, float]] = []
    for treatment in treatments:
        carbs = getattr(treatment, "carbs", None)
        ts = getattr(treatment, "created_at", None)
        fat = getattr(treatment, "fat", None)
        protein = getattr(treatment, "protein", None)
        fiber = getattr(treatment, "fiber", None)
        if carbs is None or ts is None:
            continue
        entry: dict[str, float] = {"ts": ts.isoformat(), "carbs": float(carbs)}
        if fat is not None:
            entry["fat"] = float(fat)
        if protein is not None:
            entry["protein"] = float(protein)
        if fiber is not None:
            entry["fiber"] = float(fiber)
        entries.append(entry)
    return entries


def compute_cob(now: datetime, carb_entries: Sequence[dict[str, float]], duration_hours: float = 4.0, model: str = "linear") -> float:
    if model == "carbcurves":
        total = 0.0
        for entry in carb_entries:
            total += _carbcurves_remaining(now, entry)
        return max(total, 0.0)
    return compute_cob_linear(now, carb_entries, duration_hours=duration_hours)

async def compute_cob_from_sources(
    now: datetime,
    nightscout_client,
    data_store: DataStore,
    extra_entries: list[dict[str, float]] | None = None,
    user_id: Optional[str] = None,
) -> tuple[Optional[float], dict, SourceStatus]:
    entries = []
    assumptions: list[str] = []
    cob_model = os.getenv("COB_MODEL", "linear").lower()
    source_status = SourceStatus(source="nightscout", status="unknown")
    ns_error = None
    
    # 1. Fetch Local fallback (always load for merging)
    local_events = []
    try:
        raw_events = data_store.load_events()
        for e in raw_events:
             if user_id and e.get("user_id") != user_id:
                 continue
             if e.get("carbs"):
                 local_events.append({"ts": e["ts"], "carbs": float(e["carbs"])})
    except Exception as exc:
        logger.error(f"Failed to load local events for COB: {exc}")

    entries.extend(local_events)

    # 2. Skip Fetch Nightscout (Write-Only Mode)
    ns_entries = []
    source_status.status = "ok" 
    source_status.fetched_at = now
    source_status.source = "local_only"
    
    # 3. Merge DB (Extra + Query Treatments)
    if extra_entries:
        for e in extra_entries:
            entries.append(e)

    db_entries = []
    try:
        engine = get_engine()
        if engine:
             async with AsyncSession(engine) as session:
                 cutoff = now - timedelta(hours=6)
                 cutoff_naive = cutoff.replace(tzinfo=None)
                 
                 params = {"cutoff": cutoff_naive}
                 if user_id:
                     query = text("""
                         SELECT created_at, carbs, fat, protein, fiber 
                         FROM treatments 
                         WHERE created_at > :cutoff 
                         AND carbs > 0
                         AND user_id = :user_id
                     """)
                     params["user_id"] = user_id
                 else:
                     query = text("""
                         SELECT created_at, carbs, fat, protein, fiber 
                         FROM treatments 
                         WHERE created_at > :cutoff 
                         AND carbs > 0
                     """)
                 
                 result = await session.execute(query, params)
                 rows = result.fetchall()
                 
                 for r in rows:
                     if r.created_at and r.carbs:
                         ts_iso = r.created_at.replace(tzinfo=timezone.utc).isoformat() if r.created_at.tzinfo is None else r.created_at.isoformat()
                         db_entries.append({
                             "ts": ts_iso,
                             "carbs": float(r.carbs),
                             "fat": float(getattr(r, "fat", 0) or 0),
                             "protein": float(getattr(r, "protein", 0) or 0),
                             "fiber": float(getattr(r, "fiber", 0) or 0)
                         })
    except Exception as e:
         logger.warning(f"Failed to fetch DB treatments for COB: {e}")
            
    if db_entries:
        entries.extend(db_entries)

    if ns_entries:
        for e in ns_entries:
            entries.append(e)
            
    # 5. Deduplicate
    unique_entries = []
    
    def _safe_parse(ts_val):
        try:
            val_str = str(ts_val).replace("Z", "+00:00")
            dt = datetime.fromisoformat(val_str)
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

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
        e_ins = float(e.get("insulin", 0) or 0)

        if last_e:
            l_ts = _safe_parse(last_e["ts"])
            l_val = float(last_e.get("carbs", 0))
            l_ins = float(last_e.get("insulin", 0) or 0)
            
            dt = abs((e_ts - l_ts).total_seconds())
            
            if abs(e_val - l_val) < 1.0 and abs(e_ins - l_ins) < 0.1:
                if dt < 900: is_dup = True
                elif abs(dt - 3600) < 300: is_dup = True
                elif abs(dt - 7200) < 300: is_dup = True
                
            if not is_dup and e_ins == 0 and l_ins == 0:
                 if dt < 300:
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

    cob_status: COBStatus = "unavailable"
    if unique_entries:
        cob_status = "ok" if source_status.status in ["ok", "unavailable"] else "partial"
    elif ns_error:
        # Relaxed logic: If NS failed but we checked local and found nothing, assume 0 COB.
        cob_status = "partial"
    else:
        cob_status = "ok"

    missing_macros = any(
        (e.get("fat") is None and e.get("protein") is None and e.get("fiber") is None) for e in unique_entries
    )
    effective_model = cob_model
    if cob_model == "carbcurves" and missing_macros:
        effective_model = "linear"
        assumptions.append("COB_DEFAULT_DURATION_USED")

    cob_total = compute_cob(now, unique_entries, duration_hours=4.0, model=effective_model) if unique_entries else None
    cob_info = COBInfo(
        cob_g=cob_total if cob_status in ["ok", "partial"] else None,
        status=cob_status,  # type: ignore[arg-type]
        model=effective_model,
        assumptions=assumptions,
        source=source_status.source,
        reason=ns_error,
        fetched_at=now
    )

    return cob_total, cob_info, source_status
