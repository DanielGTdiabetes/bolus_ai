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


def _boluses_from_events(events: list[dict]) -> list[dict]:
    boluses: list[dict] = []
    for event in events:
        if event.get("type") != "bolus":
            continue
            
        # Filter Basal
        evt_type = (event.get("eventType") or "").lower()
        notes = (event.get("notes") or "").lower()
        if "basal" in evt_type or "basal" in notes or "lenta" in notes:
            continue
            
        units = float(event.get("units", 0))
        ts = event.get("ts")
        if units > 0 and ts:
            event_id = event.get("id") or event.get("_id") or event.get("event_id")
            boluses.append({
                "ts": ts,
                "units": units,
                "id": str(event_id) if event_id else None,
                "source": "local_events",
                "duration": float(event.get("duration", 0) or 0),
                "entered_by": event.get("enteredBy") or event.get("entered_by"),
            })
    return boluses


def _boluses_from_treatments(treatments) -> list[dict]:
    boluses: list[dict] = []
    for treatment in treatments:
        units = getattr(treatment, "insulin", None)
        ts = getattr(treatment, "created_at", None)
        if units is None or ts is None:
            continue
        treatment_id = (
            getattr(treatment, "id", None)
            or getattr(treatment, "_id", None)
            or getattr(treatment, "event_id", None)
        )
        boluses.append({
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "units": float(units),
            "duration": float(getattr(treatment, "duration", 0) or 0),
            "id": str(treatment_id) if treatment_id else None,
            "source": "nightscout",
            "entered_by": getattr(treatment, "enteredBy", None)
            or getattr(treatment, "entered_by", None),
        })
    return boluses


def _identity_values(bolus: dict) -> set[str]:
    values = set()
    for field in ("id", "event_id", "source_id", "nightscout_id"):
        value = bolus.get(field)
        if value:
            values.add(str(value))
    aliases = bolus.get("identity_aliases") or []
    values.update(str(value) for value in aliases if value)
    return values


def _legacy_fingerprint(bolus: dict) -> tuple[str, float] | None:
    """Exact fallback for legacy records that have no persistent identity.

    We deliberately do not use time windows. Two equal doses 20, 60 or 120
    minutes apart are distinct. Only an exact normalized timestamp and dose can
    identify the same legacy record mirrored across stores.
    """
    try:
        ts = _parse_timestamp(str(bolus["ts"])).isoformat(timespec="seconds")
        return ts, round(float(bolus["units"]), 4)
    except Exception:
        return None


def _merge_unique_boluses(*sources: Sequence[dict]) -> list[dict]:
    unique: list[dict] = []
    identities: set[str] = set()
    all_fingerprints: set[tuple[str, float]] = set()
    legacy_fingerprints: set[tuple[str, float]] = set()

    for source in sources:
        for candidate in source or []:
            candidate_ids = _identity_values(candidate)
            if candidate_ids and identities.intersection(candidate_ids):
                continue

            fingerprint = _legacy_fingerprint(candidate)
            # Exact fingerprints are used when either side is legacy. Records
            # with different stable identities remain distinct by design.
            is_legacy = not candidate_ids
            # If either side has no stable identity, an exact timestamp+dose is
            # the only conservative compatibility fallback. Two records that
            # both have distinct stable identities are always kept.
            duplicate_with_legacy = bool(
                fingerprint
                and (
                    (is_legacy and fingerprint in all_fingerprints)
                    or (not is_legacy and fingerprint in legacy_fingerprints)
                )
            )
            if duplicate_with_legacy:
                continue

            unique.append(candidate)
            identities.update(candidate_ids)
            if fingerprint:
                all_fingerprints.add(fingerprint)
                if is_legacy:
                    legacy_fingerprints.add(fingerprint)

    return unique


async def _load_iob_sources(
    *,
    now: datetime,
    settings: UserSettings,
    nightscout_client,
    data_store: DataStore,
    user_id: Optional[str],
) -> tuple[list[dict], list[dict], list[dict], Optional[str], Optional[str], Optional[str]]:
    """Load authoritative and fallback IOB sources without conflating failure and zero."""
    db_boluses: list[dict] = []
    local_boluses: list[dict] = []
    ns_boluses: list[dict] = []
    db_error: Optional[str] = None
    local_error: Optional[str] = None
    ns_error: Optional[str] = None

    try:
        engine = get_engine()
        if engine is None:
            raise RuntimeError("motor de base de datos no disponible")
        async with AsyncSession(engine) as session:
            cutoff = (now - timedelta(hours=settings.iob.dia_hours + 1)).replace(tzinfo=None)
            # Never query treatments across all users when caller identity is absent.
            # A missing user_id intentionally matches no DB rows; local event sources
            # can still provide IOB for legacy/offline callers.
            params = {"cutoff": cutoff, "user_id": user_id or "__bolus_ai_no_user__"}
            user_filter = "AND user_id = :user_id"
            query = text(f"""
                SELECT id, nightscout_id, created_at, insulin, duration,
                       event_type, notes, entered_by
                FROM treatments
                WHERE created_at > :cutoff
                  AND insulin > 0
                  {user_filter}
            """)
            result = await session.execute(query, params)
            for row in result.fetchall():
                event_type = (getattr(row, "event_type", "") or "").lower()
                notes = (getattr(row, "notes", "") or "").lower()
                if "basal" in event_type or "basal" in notes or "lenta" in notes:
                    continue
                created_at = row.created_at
                if isinstance(created_at, str):
                    created_at = _parse_timestamp(created_at)
                ts = (
                    created_at.replace(tzinfo=timezone.utc).isoformat()
                    if created_at.tzinfo is None
                    else created_at.astimezone(timezone.utc).isoformat()
                )
                local_id = str(row.id) if row.id else None
                ns_id = str(row.nightscout_id) if row.nightscout_id else None
                db_boluses.append({
                    "ts": ts,
                    "units": float(row.insulin),
                    "duration": float(getattr(row, "duration", 0) or 0),
                    "id": local_id,
                    "nightscout_id": ns_id,
                    "identity_aliases": [value for value in (local_id, ns_id) if value],
                    "source": "local_db",
                    "entered_by": getattr(row, "entered_by", None),
                })
    except Exception as exc:
        db_error = f"tratamientos locales no disponibles: {exc}"
        logger.error("Failed to fetch DB treatments for IOB: %s", exc)

    try:
        local_events = data_store.load_events()
        if user_id:
            local_events = [event for event in local_events if event.get("user_id") == user_id]
        local_boluses = _boluses_from_events(local_events)
    except Exception as exc:
        local_error = f"eventos locales no disponibles: {exc}"
        logger.error("Failed to load local events for IOB: %s", exc)

    if nightscout_client is not None:
        try:
            treatments = await nightscout_client.get_recent_treatments(
                hours=math.ceil(settings.iob.dia_hours + 1),
                limit=500,
            )
            # External records without a persistent identity are not safe to
            # merge because they cannot be distinguished from local mirrors.
            parsed_ns_boluses = _boluses_from_treatments(treatments)
            ns_boluses = [
                bolus for bolus in parsed_ns_boluses if _identity_values(bolus)
            ]
            if len(ns_boluses) != len(parsed_ns_boluses):
                ns_error = (
                    "Nightscout devolvió tratamientos de insulina sin identidad estable"
                )
        except Exception as exc:
            ns_error = f"Nightscout no disponible: {exc}"
            logger.error("Failed to fetch Nightscout treatments for IOB: %s", exc)

    return db_boluses, local_boluses, ns_boluses, db_error, local_error, ns_error


from app.models.iob import IOBInfo, IOBStatus, SourceStatus, COBInfo, COBStatus

async def compute_iob_from_sources(
    now: datetime,
    settings: UserSettings,
    nightscout_client,
    data_store: DataStore,
    extra_boluses: list[dict] | None = None,
    user_id: Optional[str] = None,
    persist_cache: bool = True,
) -> tuple[Optional[float], list[dict], IOBInfo, Optional[str]]:
    """
    Computes IOB with detailed status reporting.
    Returns: (internal_iob, breakdown, iob_info, warning_msg)
    """
    profile = InsulinActionProfile(
        dia_hours=settings.iob.dia_hours,
        curve=settings.iob.curve,
        peak_minutes=settings.iob.peak_minutes,
    )

    boluses: list[dict] = []
    breakdown: list[dict] = []
    
    iob_status: IOBStatus = "unavailable"
    iob_reason: Optional[str] = None
    iob_source: str = "unknown"
    warning_msg: Optional[str] = None
    treatments_status = SourceStatus(source="nightscout", status="unknown")
    cache_iob: Optional[float] = None
    cache_ts: Optional[datetime] = None
    
    try:
        cache_path = data_store.data_dir / "iob_cache.json"
        if persist_cache or cache_path.exists():
            cache_raw = data_store.read_json("iob_cache.json", {"iob_u": None, "fetched_at": None})
            if cache_raw.get("iob_u") is not None and cache_raw.get("fetched_at"):
                cache_iob = float(cache_raw["iob_u"])
                cache_ts = datetime.fromisoformat(str(cache_raw["fetched_at"]))
    except Exception:
        cache_iob = None
        cache_ts = None
    
    (
        db_boluses,
        local_boluses,
        ns_boluses,
        db_error,
        local_error,
        ns_error,
    ) = await _load_iob_sources(
        now=now,
        settings=settings,
        nightscout_client=nightscout_client,
        data_store=data_store,
        user_id=user_id,
    )
    
    boluses = _merge_unique_boluses(
        db_boluses,
        local_boluses,
        extra_boluses or [],
        ns_boluses,
    )
    
    def _safe_parse(ts_val):
        try:
            return _parse_timestamp(str(ts_val))
        except Exception:
            logger.warning("Failed to parse IOB timestamp: %s", ts_val, exc_info=True)
            return None
    
    active_sources = ["local_db"]
    if local_boluses:
        active_sources.append("local_events")
    if ns_boluses:
        active_sources.append("nightscout")
    iob_source = "+".join(active_sources)
    treatments_status.source = iob_source
    treatments_status.fetched_at = now

    # A source failure is never converted into a known zero.
    hard_failures = [reason for reason in (db_error, ns_error) if reason]
    if hard_failures:
        iob_status = "stale" if cache_iob is not None else "unavailable"
        iob_reason = "; ".join(hard_failures)
        warning_msg = (
            f"IOB no verificable: {iob_reason}. "
            "Requiere IOB manual o confirmación."
        )
        treatments_status.status = "stale" if cache_iob is not None else "error"
    elif local_error:
        iob_status = "partial"
        iob_reason = local_error
        warning_msg = f"IOB calculado desde tratamientos persistidos; {local_error}."
        treatments_status.status = "error"
    else:
        # Zero is valid only after every required source returned successfully.
        iob_status = "ok"
        iob_reason = None
        warning_msg = None
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
                "duration": duration,
                "id": bolus.get("id"),
                "source": bolus.get("source", "unknown"),
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
    
    if persist_cache:
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
