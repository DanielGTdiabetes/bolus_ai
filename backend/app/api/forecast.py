import re
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from app.models.forecast import (
    ForecastSimulateRequest,
    ForecastResponse,
    ForecastEvents,
    ForecastEventBolus,
    ForecastEventCarbs,
    SimulationParams,
    ForecastBasalInjection,
    PredictionMeta,
    NightPatternMeta,
)
from app.services.forecast_engine import ForecastEngine
from app.core.security import get_current_user, get_current_user_optional, CurrentUser
from app.core.db import get_db_session
from app.core.settings import Settings, get_settings
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.settings_service import get_user_settings_service
from app.models.settings import UserSettings
from app.services.nightscout_secrets_service import get_ns_config
from app.services.nightscout_client import NightscoutClient
from app.services.autosens_service import AutosensService
from app.services.smart_filter import FilterConfig
from app.models.basal import BasalEntry
from app.services.dexcom_client import DexcomClient
from app.services.store import DataStore
from pathlib import Path
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.services.ml_inference_service import MLInferenceService
from app.api.ml_features import build_runtime_features

from app.services.night_pattern import (
    LOCAL_TZ,
    NightPatternContext,
    apply_night_pattern_adjustment,
    get_or_compute_pattern,
    sustained_rise_detected,
    trend_slope_from_series,
)

router = APIRouter()

def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))

@router.get("/current", response_model=ForecastResponse, summary="Get ambient forecast based on current status")
async def get_current_forecast(
    user: Optional[CurrentUser] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_db_session),
    store: DataStore = Depends(_data_store),
    settings: Settings = Depends(get_settings),
    start_bg_param: Optional[float] = Query(None, alias="start_bg", description="Override start BG if known by client"),
    future_insulin_u: Optional[float] = Query(None, description="Future planned insulin units (e.g. dual bolus remainder)"),
    future_insulin_delay_min: Optional[int] = Query(0, description="Delay in minutes for future insulin"),
    future_insulin_duration_min: Optional[int] = Query(0, description="Duration in minutes for future insulin (square wave)")
):
    """
    Auto-generates a forecast based on:
    - Current BG (from Nightscout)
    - Active IOB/COB (from DB Treatments)
    - User Settings (ISF/ICR)
    """
    def compute_warsaw_equivalent_carbs(fat_g: float, protein_g: float, warsaw_cfg):
        """
        Convert fat/protein grams into Warsaw-equivalent carbs for Forecast.
        Mirrors the bolus engine logic:
        - grams = (fat*9 + protein*4) / 10
        - apply safety factor (simple/dual)
        - set absorption to 3-5h based on FPU size
        """
        if not warsaw_cfg or not warsaw_cfg.enabled:
            return None
        if (fat_g or 0) <= 0 and (protein_g or 0) <= 0:
            return None

        total_extra_kcal = (fat_g or 0) * 9.0 + (protein_g or 0) * 4.0
        if total_extra_kcal <= 0:
            return None

        fpu_equivalent_carbs = total_extra_kcal / 10.0
        if fpu_equivalent_carbs <= 0:
            return None

        if fpu_equivalent_carbs < 20:
            absorption = 180
        elif fpu_equivalent_carbs < 40:
            absorption = 240
        else:
            absorption = 300

        is_dual = total_extra_kcal >= warsaw_cfg.trigger_threshold_kcal
        factor = warsaw_cfg.safety_factor_dual if is_dual else warsaw_cfg.safety_factor
        effective_carbs = fpu_equivalent_carbs * factor

        if effective_carbs <= 0:
            return None

        return {
            "grams": effective_carbs,
            "absorption": absorption,
            "is_dual": is_dual,
        }

    split_note_regex = re.compile(
        r"split:\s*([0-9]+(?:\.[0-9]+)?)\s*now\s*\+\s*([0-9]+(?:\.[0-9]+)?)\s*delayed\s*([0-9]+)m",
        re.IGNORECASE,
    )

    username = user.username if user else "admin"

    # 1. Load Settings
    user_settings = None
    try:
        data = await get_user_settings_service(username, session)
        if data and data.get("settings"):
            user_settings = UserSettings.migrate(data["settings"])
    except Exception:
        pass
        
    if not user_settings:
        raise HTTPException(status_code=400, detail="Settings not found")

    # 2. Fetch Current BG & History (NS)
    ns_config = await get_ns_config(session, username)
    # Default fallback or explicit override
    start_bg = start_bg_param

    
    recent_bg_series = []
    cgm_source = None
    
    if ns_config and ns_config.enabled and ns_config.url:
        try:
            client = NightscoutClient(ns_config.url, ns_config.api_secret)
            
            # Fetch last 45 minutes to calculate momentum
            # We buffer the "now" (end search) by +20 mins to account for clock skew where
            # the uploader device is ahead of the server, otherwise we miss the "latest" point.
            now_utc = datetime.now(timezone.utc)
            start_search = now_utc - timedelta(minutes=45)
            end_search = now_utc + timedelta(minutes=20)
            
            history_sgvs = await client.get_sgv_range(start_search, end_search, count=20)
            
            if history_sgvs:
                # Sort by date descending (latest first) to find current easily
                history_sgvs.sort(key=lambda x: x.date, reverse=True)
                
                # Use the very latest as start_bg IF not overridden
                if start_bg_param is None:
                    start_bg = float(history_sgvs[0].sgv)
                cgm_source = "nightscout"
                
                # Build series for momentum
                # ForecastEngine expects: [{'minutes_ago': 0, 'value': 120}, ...]
                for entry in history_sgvs:
                    # Calculate minutes ago
                    entry_ts = entry.date / 1000.0
                    mins_ago = (now_utc.timestamp() - entry_ts) / 60.0
                    
                    # Clamp future points (skew) to 0 to avoid logic errors in Engine
                    if mins_ago < 0:
                        mins_ago = 0.0

                    if 0 <= mins_ago <= 60: # Sanity check
                        recent_bg_series.append({
                            "minutes_ago": -1 * mins_ago, # Engine expects negative for past?
                            # Wait, forecast_engine.py _calculate_momentum says:
                            # "t = -1 * abs(p.get('minutes_ago', 0)) # t must be negative (past)"
                            # And the input Description says "minutes_ago': 0" (positive scalar).
                            # Let's pass positive "minutes ago" and let engine negate it, or pass 0.
                            # forecast_engine.py line 309: t = -1 * abs(p.get('minutes_ago', 0))
                            # So if I pass 5, it becomes -5. Correct.
                            # So I should pass POSITIVE minutes_ago here.
                            
                            "minutes_ago": mins_ago,
                            "value": float(entry.sgv)
                        })
                
            await client.aclose()
        except Exception as e:
            print(f"NS Fetch failed: {e}")
            pass

    # 2.2 Dexcom Fallback (if Start BG still missing)
    if start_bg is None and user_settings and user_settings.dexcom and user_settings.dexcom.username:
        try:
             # Use cached/shared client if possible, or new one
             dex = DexcomClient(
                 username=user_settings.dexcom.username,
                 password=user_settings.dexcom.password,
                 region=user_settings.dexcom.region or "ous"
             )
             reading = await dex.get_latest_sgv()
             if reading:
                 start_bg = float(reading.sgv)
                 cgm_source = "dexcom"
                 # We cannot build momentum history from single point, but we have start_bg.
                 # Momentum will implicitly be 0.
        except Exception as e:
             print(f"Dexcom Fetch failed: {e}")
    
    # 2.3 Final Fallback: Manual or Previous Checkin?
    # TODO: Could read from basal_checkin if < 10 mins old? 
    # For now, if None, engine might error or use 120 default.


    # 3. Fetch Treatments (Last 6 hours)
    from app.models.treatment import Treatment
    from sqlalchemy import select
    # datetime imports moved to top level
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    
    # 3.0 Fetch DB Treatments
    stmt = (
        select(Treatment)
        .where(Treatment.user_id == username)
        .where(Treatment.created_at >= cutoff.replace(tzinfo=None)) # DB assumes naive usually
        .order_by(Treatment.created_at.desc())
    )
    result = await session.execute(stmt)
    db_rows = result.scalars().all()

    # 3.1 OLD: Fetch NS Treatments (External Data) - REMOVED BY USER REQUEST
    # We rely 100% on Local DB to avoid duplication and sync issues.
    ns_rows = []
    # (NS connection code removed)

    # 3.2 Merge & Deduplicate
    all_rows = []
    all_rows.extend(db_rows)
    all_rows.extend(ns_rows)
    
    # Sort by created_at
    all_rows.sort(key=lambda x: x.created_at if x.created_at.tzinfo else x.created_at.replace(tzinfo=timezone.utc))

    unique_rows = []
    if all_rows:
        last_row = None
        for row in all_rows:
            # Prepare row properties
            r_time = row.created_at
            if r_time.tzinfo is None: r_time = r_time.replace(tzinfo=timezone.utc)
            r_ins = getattr(row, 'insulin', 0) or 0
            r_carbs = getattr(row, 'carbs', 0) or 0
            
            is_dup = False
            
            if last_row:
                l_time = last_row.created_at
                if l_time.tzinfo is None: l_time = l_time.replace(tzinfo=timezone.utc)
                l_ins = getattr(last_row, 'insulin', 0) or 0
                l_carbs = getattr(last_row, 'carbs', 0) or 0
                
                dt_diff = abs((r_time - l_time).total_seconds())
                
                # Check 1: Exact Duplicate (Same Insulin AND Same Carbs)
                values_match = (abs(r_ins - l_ins) < 0.1) and (abs(r_carbs - l_carbs) < 1.0)
                
                if values_match:
                    # 2 mins proximity OR Timezone shift (1h, 2h)
                    if dt_diff < 120 or abs(dt_diff - 3600) < 120 or abs(dt_diff - 7200) < 120:
                        is_dup = True
                
                # Check 2: Carb Collision (Update Logic) - ONLY if both have NO insulin
                # If we have two carb entries close in time, assume it's an update (e.g. 45 -> 60)
                # We KEEP the one with higher carbs (assuming it's the accumulated total like MPF)
                if not is_dup and r_ins == 0 and l_ins == 0:
                     if dt_diff < 1200: # Within 20 minutes
                         # It's a collision. We want to keep the one with MAX carbs.
                         # 'row' is the current candidate. 'last_row' is the one already in unique_rows[-1].
                         if r_carbs > l_carbs:
                             # Current is better (updated total). Replace the last one.
                             unique_rows.pop() # Remove the smaller/old one
                             unique_rows.append(row) # Add the new bigger one
                             last_row = row
                             is_dup = True # Handled, don't add again
                         else:
                             # Previous was better or equal. Ignore current.
                             is_dup = True 

                # Check 3: Bolus Covering Carb Entry (Deduplication)
                # If we have a Carb-only entry followed by a Bolus entry with ~same carbs, 
                # assume the bolus "covers" the carb entry and they are duplicates (user flow: Log -> Bolus).
                # last_row = Carb Only, row = Bolus (Carbs+Insulin)
                if not is_dup and l_ins == 0 and r_ins > 0 and r_carbs > 0:
                    if dt_diff < 3600: # 60 minutes window
                         if abs(r_carbs - l_carbs) <= 10: # Allow 10g variances (e.g. estimation diffs)
                             # The Bolus entry (row) is the "Master" one. Remove the Carb-only entry.
                             unique_rows.pop()
                             unique_rows.append(row)
                             last_row = row
                             is_dup = True
                
                # Check 3b: Reverse Order (Bolus then Carb Entry, e.g. async sync)
                # Ignore the redundant Carb entry.
                if not is_dup and l_ins > 0 and l_carbs > 0 and r_ins == 0:
                    if dt_diff < 3600:
                        if abs(r_carbs - l_carbs) <= 10:
                            is_dup = True 
            
            if not is_dup:
                unique_rows.append(row)
                last_row = row
        
    rows = unique_rows

    boluses = []
    carbs = []
    # Initialize basal_injections early to collect both from Treatments (candidates) and BasalEntry
    basal_injections = []
    
    now_utc = datetime.now(timezone.utc)
    
    # Helper to resolve slot
    def get_slot_params(h: int, settings: UserSettings):
        # Default to Lunch if unknown
        icr = settings.cr.lunch
        isf = settings.cf.lunch
        absorption = settings.absorption.lunch
        
        # Use User Configured Schedule
        # Schedule defines START hours. 
        # e.g. Breakfast 5, Lunch 13, Dinner 20.
        
        # Sort hours to handle crossover/ordering simply
        s_bk = settings.schedule.breakfast_start_hour
        s_ln = settings.schedule.lunch_start_hour
        s_dn = settings.schedule.dinner_start_hour
        
        # Determine slot
        if s_bk <= h < s_ln:
            icr = settings.cr.breakfast
            isf = settings.cf.breakfast
            absorption = settings.absorption.breakfast
        elif s_ln <= h < s_dn:
             icr = settings.cr.lunch
             isf = settings.cf.lunch
             absorption = settings.absorption.lunch
        elif h >= s_dn or h < s_bk:
             # Dinner covers late night and early morning before breakfast
             # Note: For strict "Snack" slots or "Night" slots we assume Dinner settings apply 
             # unless we add explicit Night slot.
             # If h < s_bk (e.g. 04:00), it's technically "Night" or "Late Dinner".
             icr = settings.cr.dinner
             isf = settings.cf.dinner
             absorption = settings.absorption.dinner 
             
        return float(icr), float(isf), int(absorption)

    now_utc = datetime.now(timezone.utc)
    
    for row in rows:
        # Calculate offset in minutes
        # created_at is naive UTC in DB usually
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
            
        diff_min = (now_utc - created_at).total_seconds() / 60.0
        # offset must be negative for past events
        offset = -1 * diff_min
        
        # Determine Hour in User Time
        user_hour = (created_at.hour + 1) % 24 # Fallback
        if user_settings.timezone:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(user_settings.timezone)
                user_hour = created_at.astimezone(tz).hour
            except Exception:
                pass 

        evt_icr, _, base_absorption = get_slot_params(user_hour, user_settings)
        
        if row.insulin and row.insulin > 0:
            # SAFETY FILTER: Exclude Basal treated as Bolus
            # If notes or event_type indicate basal, skip bolus addition.
            is_basal_kw = False
            notes_lower = (row.notes or "").lower()
            evt_lower = (getattr(row, 'event_type', "") or "").lower()
            
            if "basal" in notes_lower or "tresiba" in notes_lower or "lantus" in notes_lower or "toujeo" in notes_lower or "levemir" in notes_lower:
                is_basal_kw = True
            if "basal" in evt_lower or "temp" in evt_lower:
                is_basal_kw = True

            if is_basal_kw:
                # Promote to Basal Injection Logic
                # If this treatment is actually a Basal, we add it to basal_injections
                # Assumption: If duration is 0, default to 24h (1440 min) for common basals
                # Try to guess type from notes
                b_type = "glargine"
                b_dur = 1440
                if "toujeo" in notes_lower: b_type = "toujeo"
                elif "levemir" in notes_lower: 
                    b_type = "levemir"
                    b_dur = 720 # 12h default?
                elif "tresiba" in notes_lower: 
                    b_type = "tresiba"
                    b_dur = 2500 # >24h
                
                # Check for explicit duration in row
                row_dur = getattr(row, "duration", 0.0) or 0.0
                if row_dur > 60:
                     b_dur = row_dur

                # Add candidate (we will dedupe later against official BasalEntry items)
                basal_injections.append(ForecastBasalInjection(
                    time_offset_min=int(offset),
                    units=row.insulin,
                    duration_minutes=b_dur,
                    type=b_type
                ))

            else:
                dur = getattr(row, "duration", 0.0) or 0.0
                boluses.append(ForecastEventBolus(
                    time_offset_min=int(offset), 
                    units=row.insulin,
                    duration_minutes=dur
                ))

            if dur <= 0 and row.notes:
                match = split_note_regex.search(row.notes or "")
                if match:
                    try:
                        later_u = float(match.group(2))
                        delay_min = int(float(match.group(3)))
                        if later_u > 0 and delay_min >= 0:
                            boluses.append(ForecastEventBolus(
                                time_offset_min=int(offset + delay_min),
                                units=later_u,
                                duration_minutes=dur
                            ))
                    except Exception:
                        pass
            
        if row.carbs and row.carbs > 0:
            evt_abs = base_absorption

            # Alcohol Check
            if row.notes and "alcohol" in row.notes.lower():
                evt_abs = 480 # 8 hours for alcohol
            
            # Dual Bolus Check (Persistent Memory)
            # If the notes say "Dual", it's a slow meal (Pizza/Fat), so we use 6h absorption.
            # This ensures correctness even after the "Active Plan" finishes.
            # Dual Bolus Check (Persistent Memory)
            # If the notes say "Dual", it's a slow meal (Pizza/Fat), so we use 6h absorption.
            # This ensures correctness even after the "Active Plan" finishes.
            elif row.notes and ("dual" in row.notes.lower() or "combo" in row.notes.lower()):
                evt_abs = 360
            elif row.notes and "split" in row.notes.lower():
                evt_abs = 300 # 5 hours for split if not explicitly dual

            carbs.append(ForecastEventCarbs(
                time_offset_min=int(offset), 
                grams=row.carbs,
                icr=evt_icr,
                absorption_minutes=evt_abs,
                fat_g=getattr(row, 'fat', 0) or 0,
                protein_g=getattr(row, 'protein', 0) or 0,
                fiber_g=getattr(row, 'fiber', 0) or 0
            ))

        # Avoid double counting: ForecastEngine acts on fat/protein attached to the main carb event.
        # Only add a separate Warsaw entry if there were NO carbs (so no main event to carry the macros).
        if not (row.carbs and row.carbs > 0):
            warsaw_equiv = compute_warsaw_equivalent_carbs(
                getattr(row, "fat", 0) or 0,
                getattr(row, "protein", 0) or 0,
                user_settings.warsaw if user_settings else None
            )
            if warsaw_equiv:
                carbs.append(ForecastEventCarbs(
                    time_offset_min=int(offset),
                    grams=warsaw_equiv["grams"],
                    icr=evt_icr,
                    absorption_minutes=warsaw_equiv["absorption"],
                    fat_g=getattr(row, "fat", 0) or 0,
                    protein_g=getattr(row, "protein", 0) or 0,
                    fiber_g=getattr(row, "fiber", 0) or 0
                ))




    # 3.3. Fetch Basal History (Last 48h) from BasalEntry (Official Source)
    # These are preferred over generic Treatments.
    try:
        basal_cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        stmt_basal = (
            select(BasalEntry)
            .where(BasalEntry.user_id == username)
            .where(BasalEntry.created_at >= basal_cutoff.replace(tzinfo=None))
            .order_by(BasalEntry.created_at.desc())
        )
        result_basal = await session.execute(stmt_basal)
        basal_rows = result_basal.scalars().all()
        
        for row in basal_rows:
            b_created_at = row.created_at
            if b_created_at.tzinfo is None:
                b_created_at = b_created_at.replace(tzinfo=timezone.utc)
            
            # Offset
            b_diff_min = (datetime.now(timezone.utc) - b_created_at).total_seconds() / 60.0
            b_offset = -1 * b_diff_min
            
            dur = (row.effective_hours or 24) * 60
            b_type = row.basal_type if row.basal_type else "glargine"
            
            # Deduplication: Check if we already have a similar injection from Treatments
            # (Time approx match + Units match)
            is_covered = False
            for existing in basal_injections:
                if abs(existing.units - row.dose_u) < 0.1:
                    if abs(existing.time_offset_min - int(b_offset)) < 120: # 2h wide window for manual confusion
                         # Existing (from Treatment) is basically this one.
                         # Update existing with better metadata? Or replace?
                         # Usually BasalEntry is better. Replace/Update existing properties.
                         existing.duration_minutes = dur
                         existing.type = b_type
                         # Sync time?
                         is_covered = True
                         break
            
            if not is_covered:
                basal_injections.append(ForecastBasalInjection(
                    time_offset_min=int(b_offset),
                    units=row.dose_u,
                    duration_minutes=dur,
                    type=b_type
                ))
            
    except Exception as e:
        print(f"Forecast Basal Fetch Error: {e}")
        pass
    
    # Initialize current parameters for the simulation
    now_hour = (datetime.now(timezone.utc).hour + 1) % 24
    curr_icr, curr_isf, _ = get_slot_params(now_hour, user_settings)

    # 3.4 Calculate Autosens (if enabled)
    # We do this logic right before constructing final simulation params
    autosens_ratio = 1.0
    if user_settings.autosens.enabled:
         try:
             # We need to await it. Service is async.
             compression_config = FilterConfig(
                 enabled=user_settings.nightscout.filter_compression,
                 night_start_hour=user_settings.nightscout.filter_night_start_hour,
                 night_end_hour=user_settings.nightscout.filter_night_end_hour,
                 treatments_lookback_minutes=user_settings.nightscout.treatments_lookback_minutes,
             )
             res = await AutosensService.calculate_autosens(
                 username,
                 session,
                 user_settings,
                 compression_config=compression_config
             )
             autosens_ratio = res.ratio
             # Log or append to response warnings/info?
             # For now just apply it silently to improve graph accuracy.
         except Exception as e:
             print(f"Forecast Autosens Error: {e}")
             
    # Apply to current params
    curr_icr = curr_icr / autosens_ratio
    curr_isf = curr_isf / autosens_ratio

    # 3.5. Add Future Planned Insulin (Dual Bolus Remainder)
    if future_insulin_u and future_insulin_u > 0:
        boluses.append(ForecastEventBolus(
            time_offset_min=future_insulin_delay_min, 
            units=future_insulin_u,
            duration_minutes=future_insulin_duration_min
        ))
        
        # SMART ADJUSTMENT:
        # If there is a dual bolus active OR high fat/protein content, extend absorption.
        # Strategy: 
        # 1. If 'dual' or 'split' keyword in notes, force 240min (4h) minimum.
        # 2. If Warsaw equivalent carbs existed (high fat/protein), ensure main carbs are also slow (e.g. 300min).
        # 3. If "Future Insulin" (active dual) is present, we are definitely in a slow meal scenario -> 360min.
    # 3. Adjust Carbs Absorption (Dynamic)
    has_warsaw_trigger = False
    
    if carbs:
        # Check for Alcohol Mode first
        # Treat alcohol separate from meal carbs
        
        has_warsaw_trigger = any(c for c in carbs if (getattr(c, 'is_dual', False) or (c.absorption_minutes and c.absorption_minutes >= 300)) and (c.time_offset_min + c.absorption_minutes > 0))
        
        for c in carbs:
            # Skip if alcohol (priority)
            if c.absorption_minutes == 480: 
                continue

            # Case A: Dual Bolus Active (Future Insulin pending)
            if future_insulin_u and future_insulin_u > 0:
                 if c.grams > 10 and c.time_offset_min > -240: # Extended window to 4h to catch the meal
                      # If we are extending insulin, we MUST extend carbs to match kinetics.
                      # Otherwise -> Hypo (Fast insulin vs Med Carbs) or Hyper (Late).
                      # We align to the bolus duration if it's longer than standard
                      target_abs = max(360, future_insulin_duration_min + 60) if future_insulin_duration_min > 0 else 360
                      c.absorption_minutes = max(getattr(c, 'absorption_minutes', 0), target_abs)
            
            # Case B: High Fat/Protein detected (Warsaw Trigger)
            # If the meal triggered Warsaw logic, the main carbs should also be slow?
            # User request: "subirlo a 4h o a la que creamos oportuno... proporcional".
            elif has_warsaw_trigger and c.grams > 10 and c.time_offset_min > -60:
                 # Standardize to 5h (300min) for heavy meals
                 c.absorption_minutes = max(getattr(c, 'absorption_minutes', 0), 300)

            pass

    # Flag for UI
    is_slow_absorption = False
    slow_reason = None
    
    if future_insulin_u and future_insulin_u > 0:
        is_slow_absorption = True
        slow_reason = "Bolo Dual Pendiente"
    elif has_warsaw_trigger:
        is_slow_absorption = True
        slow_reason = "Comida Grasa / Dual"
        
    # Check specificity
    for c in carbs:
         # Only flag if currently active
         if c.absorption_minutes and c.absorption_minutes >= 300 and (c.time_offset_min + c.absorption_minutes > 0):
             is_slow_absorption = True
             time_ago_h = abs(c.time_offset_min) / 60.0 if c.time_offset_min < 0 else 0
             
             if c.absorption_minutes == 480:
                 slow_reason = f"Modo Alcohol (8h - hace {time_ago_h:.1f}h)"
             elif c.absorption_minutes >= 300:
                 slow_reason = f"Absorción Lenta ({c.absorption_minutes/60:.1f}h - hace {time_ago_h:.1f}h)"
             break

    if is_slow_absorption and not slow_reason:
        slow_reason = "Absorción Lenta Activa"

    # 4. Construct Request
    # Current params
    now_user_hour = (now_utc.hour + 1) % 24
    if user_settings.timezone:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(user_settings.timezone)
            now_user_hour = now_utc.astimezone(tz).hour
        except Exception:
            pass

    curr_icr, curr_isf, curr_abs = get_slot_params(now_user_hour, user_settings)
    
    # Check Sick Mode (Resistance)
    try:
        sick_stmt = (
            select(Treatment)
            .where(Treatment.user_id == username)
            .where(Treatment.event_type == 'Note')
            .where(Treatment.notes.like('Sick Mode%'))
            .order_by(Treatment.created_at.desc())
            .limit(1)
        )
        sick_res = await session.execute(sick_stmt)
        last_sick = sick_res.scalars().first()
        if last_sick and "Start" in last_sick.notes:
            # Apply 30% resistance (requires ~1.3x more insulin, so ISF/ICR decrease)
            factor = 1.3
            curr_icr = curr_icr / factor
            curr_isf = curr_isf / factor
    except Exception:
        pass
    
    # NOTE: We removed the legacy "dynamic_absorption" based on carb amount (<20g).
    # Now we strictly follow the user's per-slot absorption setting.
    # If the user wants snacks to be faster, they should set "snack" absorption lower 
    # and ensure snacks are logged in snack slots (or just accept meal absorption).

    # Calculate Reference Basal (Smart Hybrid Logic)
    # 1. Intentional Dose (Standard): If user injected < 26h ago, trust that dose is correct.
    #    Ref = Current Activity. Net = 0. (Eliminates Drift).
    # 2. Forgotten Dose (Alert): If > 26h since last injection, assume they forgot.
    #    Ref = Last Known Dose. Net = 0 - Ref = Negative. (Predicts Rise).
    
    avg_basal = 0.0
    try:
        from app.services.math.basal import BasalModels
        
        # 1. Calculate Real Activity at T=0
        current_activity = 0.0
        if basal_injections:
            for b_inj in basal_injections:
                t_since = 0 - b_inj.time_offset_min
                rate = BasalModels.get_activity(
                    t_since,
                    b_inj.duration_minutes or 1440,
                    b_inj.type,
                    b_inj.units
                )
                current_activity += rate
        
        # 2. Check Freshness (Last 26h)
        last_injection_time = None
        last_dose_u = 0.0
        
        # Use basal_rows (Official History) to find last injection
        if basal_rows:
            # defined in 3.3, sorted desc
            last_entry = basal_rows[0] 
            last_injection_time = last_entry.created_at
            if last_injection_time.tzinfo is None:
                last_injection_time = last_injection_time.replace(tzinfo=timezone.utc)
            last_dose_u = last_entry.dose_u
        
        # Fallback: Check simple treatments if basal_rows empty (rare)
        if not last_injection_time:
             # scan basal_injections
             pass 

        is_recent_active = False
        if last_injection_time:
             hours_ago = (datetime.now(timezone.utc) - last_injection_time).total_seconds() / 3600.0
             if hours_ago < 26:
                 is_recent_active = True
        
        print(f"Basal Logic: Last={last_dose_u}U, {hours_ago if last_injection_time else 'N/A'}h ago. Recent={is_recent_active}")

        # LOGIC RESTORED (SMART HYBRID V3):
        # We need to warn the user if they have truly FORGOTTEN the basal (0 activity),
        # but NOT punish them if they just shifted the time or reduced the dose (Intentional).
        
        # Threshold: If you have less than 5% of your usual basal active, we assume it's missing.
        # Otherwise, we assume whatever level you have is Intentional.
        
        threshold_u = last_dose_u * 0.05 # 5% (Very permissive)
        daily_activity = current_activity * 1440.0
        
        if (daily_activity > threshold_u) or (last_dose_u == 0):
             # Intentional Mode: You have some insulin, so we trust it's enough.
             # Ref = Activity -> Net = 0.
             avg_basal = daily_activity
        else:
             # Forgotten/Empty Mode: You have almost ZERO insulin.
             # This is dangerous. We predict a rise based on what you *should* have.
             # Ref = Usual Dose -> Net = Negative -> Rise.
             avg_basal = last_dose_u
             if avg_basal == 0: avg_basal = 15.0 # Fallback default

    except Exception as e:
        print(f"Basal Ref Calc Error: {e}")
        avg_basal = 0.0


    # Master Plan: Sincronización de DIA para Fiasp (Evita falsas hipos)
    dia_val = user_settings.iob.dia_hours
    dia_overridden = False
    if user_settings.iob.curve.lower() == "fiasp" and dia_val < 5.0:
        # Recomendación técnica: En simulación biexponencial, Fiasp necesita cola de 5.5h
        dia_val = 5.5
        dia_overridden = True

    sim_params = SimulationParams(
        isf=curr_isf,
        icr=curr_icr, 
        dia_minutes=int(dia_val * 60),
        carb_absorption_minutes=curr_abs,
        insulin_peak_minutes=user_settings.iob.peak_minutes,
        insulin_model=user_settings.iob.curve,
        basal_daily_units=avg_basal,
        warsaw_factor_simple=user_settings.warsaw.safety_factor if user_settings.warsaw else 1.0, # Default to 1.0 for Trust logic
        warsaw_trigger=user_settings.warsaw.trigger_threshold_kcal if user_settings.warsaw else 50,
        use_fiber_deduction=user_settings.calculator.subtract_fiber if user_settings.calculator else False,
        fiber_factor=user_settings.calculator.fiber_factor if user_settings.calculator else 0.0,
        target_bg=float(user_settings.targets.mid) if (user_settings and user_settings.targets) else 110.0
    )
    
    # Import locally if not at top, or ensure top imports are enough
    # MomentumConfig is in app.models.forecast
    # 4. Construct Request
    from app.models.forecast import MomentumConfig # Ensure imported

    # Disable momentum if we are in a "Dual Bolus" / Futures scenario
    # This prevents noise/artifacts (like compression recovery) from projecting a massive spike
    # on top of the already complex carb/insulin interaction. We trust the "Physics" (Carbs vs Insulin) more here.
    use_momentum = True
    if future_insulin_u and future_insulin_u > 0:
        use_momentum = False

    # Calculate Resistance Multiplier (If not provided)
    # Based on Ratio of Current ISF vs Reference ISF (Lunch)
    # e.g. Breakfast ISF 40, Lunch 100 -> Ratio 0.4 -> Multiplier 0.4 (Resistance)
    if sim_params.insulin_sensitivity_multiplier is None and user_settings and user_settings.cf:
        try:
            # Reference: Lunch ISF (Correction Factor)
            isf_ref = float(user_settings.cf.lunch) if user_settings.cf.lunch else 0.0
            
            # Current Slot ISF (Resolved for current time)
            isf_slot = curr_isf 
            
            if isf_ref > 0 and isf_slot > 0:
                ratio = isf_slot / isf_ref
                # Clamp: Min 0.4 (High Resistance), Max 1.2 (High Sensitivity)
                multiplier = max(0.4, min(1.2, ratio))
                sim_params.insulin_sensitivity_multiplier = multiplier
                
                # Debug Logging
                import os
                if os.environ.get("PREDICTION_DEBUG", "false").lower() == "true":
                    print(f"DEBUG_RESISTANCE (ISF): isf_ref={isf_ref} isf_slot={isf_slot} ratio={ratio:.2f} mult={multiplier:.2f}")
        except Exception as e:
            print(f"Resistance Calc Error (ISF): {e}")
            pass

    # Apply Insulin Onset Delay (Physiological Lag)
    # Shifts all rapid boluses into the future by onset_min (e.g. 10m)
    onset_val = sim_params.insulin_onset_minutes or 0
    if onset_val > 0:
        for bolus in boluses:
            if bolus.time_offset_min > 0:
                bolus.time_offset_min += onset_val

    payload = ForecastSimulateRequest(
        start_bg=start_bg,
        params=sim_params,
        events=ForecastEvents(boluses=boluses, carbs=carbs, basal_injections=basal_injections),
        momentum=MomentumConfig(enabled=use_momentum, lookback_points=5),
        recent_bg_series=recent_bg_series if recent_bg_series else None
    )
    
    response = ForecastEngine.calculate_forecast(payload)
    response.slow_absorption_active = is_slow_absorption
    response.slow_absorption_reason = slow_reason
    
    # Transparency Metadata
    if response.meta is None:
        response.meta = {}
    
    response.meta.update({
        "effective_dia_hours": dia_val,
        "dia_overridden": dia_overridden,
        "dia_reason": "fiasp_min_dia_for_sim" if dia_overridden else None
    })

    # --- IOB/COB & ML Preparation ---
    iob_total = 0.0
    cob_total = 0.0
    iob_info = None
    cob_info = None
    
    # We fetch IOB/COB now for both ML and NightPattern to ensure consistency
    try:
        ns_client_for_iob = (
            NightscoutClient(ns_config.url, ns_config.api_secret)
            if ns_config and ns_config.enabled and ns_config.url
            else None
        )
        try:
             iob_total, _, iob_info, _ = await compute_iob_from_sources(
                 now=datetime.now(timezone.utc),
                 settings=user_settings,
                 nightscout_client=ns_client_for_iob,
                 data_store=store,
                 extra_boluses=None,
                 user_id=username,
             )
             cob_total, cob_info, _ = await compute_cob_from_sources(
                 now=datetime.now(timezone.utc),
                 nightscout_client=ns_client_for_iob,
                 data_store=store,
                 extra_entries=None,
                 user_id=username,
             )
        finally:
             if ns_client_for_iob:
                 await ns_client_for_iob.aclose()
    except Exception as e:
        print(f"IOB/COB Calc failed: {e}")

    # [ML Inference Real]
    try:
        ml_svc = MLInferenceService.get_instance()
        ml_svc.load_models()
        
        if ml_svc.models_loaded:
             # Prepare Inputs
             # Trend: Try to infer or default
             ml_trend = "Flat" 
             # todo: can we get direction from recent_bg_series if we enriched it?
             
             # Age
             calc_age = 0.0
             if recent_bg_series:
                 calc_age = recent_bg_series[0].get('minutes_ago', 0)

             # Build Features
             feats = build_runtime_features(
                 user_id=username,
                 now_utc=datetime.now(timezone.utc),
                 bg_mgdl=start_bg,
                 trend=ml_trend,
                 bg_age_min=calc_age,
                 iob_u=iob_total or 0.0,
                 cob_g=cob_total or 0.0,
                 to_utc_func=lambda d: d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc),
                 basal_rows=basal_rows,
                 treatment_rows=unique_rows, 
                 iob_status=iob_info.status if iob_info else "unknown",
                 cob_status=cob_info.status if cob_info else "unknown",
                 source_ns_enabled=bool(ns_config and ns_config.enabled),
                 ns_treatments_count=0 # Not tracked in this context easily
             )
             
             pred = ml_svc.predict(feats, response.series)
             
             if pred.ml_ready:
                 response.ml_ready = True
                 response.ml_series = pred.predicted_series
                 response.p10_series = pred.p10_series
                 response.p90_series = pred.p90_series
                 response.confidence_score = pred.confidence_score
                 
    except Exception as ml_e:
        print(f"ML Inference skipped: {ml_e}")
    
    # If we added future insulin, run a baseline simulation (without it) for comparison
    if future_insulin_u and future_insulin_u > 0:
        # Remove the last bolus (which is the future one we added)
        # We need a deep copy or just modify the list if we don't reuse payload.
        # But payload is Pydantic.
        from copy import deepcopy
        payload_base = deepcopy(payload)
        if payload_base.events.boluses:
             payload_base.events.boluses.pop() # Remove the last one
        
        response_base = ForecastEngine.calculate_forecast(payload_base)
        response.baseline_series = response_base.series
    pattern_meta = NightPatternMeta(enabled=settings.night_pattern.enabled, applied=False)
    if settings.night_pattern.enabled:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(LOCAL_TZ)
        draft = None

        meal_recent = False
        bolus_recent = False
        last_meal_high_fat_protein = False

        meal_cutoff = now_utc - timedelta(hours=settings.night_pattern.meal_lookback_h)
        bolus_cutoff = now_utc - timedelta(hours=settings.night_pattern.bolus_lookback_h)

        for row in unique_rows:
            r_time = row.created_at
            if r_time.tzinfo is None:
                r_time = r_time.replace(tzinfo=timezone.utc)
            if (row.carbs or 0) > 0 and r_time >= meal_cutoff:
                meal_recent = True
                if (row.fat or 0) + (row.protein or 0) >= 25:
                    last_meal_high_fat_protein = True
            if (row.insulin or 0) > 0 and r_time >= bolus_cutoff:
                bolus_recent = True

        ns_client_for_iob = None # Cleanup check
        # IOB/COB already calculated above


        trend_slope = trend_slope_from_series(recent_bg_series)
        sustained_rise = sustained_rise_detected(recent_bg_series)
        slow_digestion_signal = bool(
            meal_recent
            or draft is not None
            or (cob_total is not None and cob_total > 1.0)
        )

        context = NightPatternContext(
            draft_active=draft is not None,
            meal_recent=meal_recent,
            bolus_recent=bolus_recent,
            iob_u=iob_total if iob_info.status in ["ok", "partial"] else None,
            cob_g=cob_total if cob_info.status in ["ok", "partial"] else None,
            trend_slope=trend_slope,
            sustained_rise=sustained_rise,
            slow_digestion_signal=slow_digestion_signal,
            last_meal_high_fat_protein=last_meal_high_fat_protein,
        )

        if not cgm_source:
            if ns_config and ns_config.enabled and ns_config.url:
                cgm_source = "nightscout"
            elif user_settings and user_settings.dexcom and user_settings.dexcom.username:
                cgm_source = "dexcom"

        cgm_entries = []
        if cgm_source == "nightscout" and ns_config and ns_config.enabled and ns_config.url:
            client = NightscoutClient(ns_config.url, ns_config.api_secret)
            start_range = now_utc - timedelta(days=settings.night_pattern.days)
            end_range = now_utc
            try:
                sgvs = await client.get_sgv_range(start_range, end_range, count=5000)
                cgm_entries = [
                    (datetime.fromtimestamp(s.date / 1000, tz=timezone.utc), float(s.sgv)) for s in sgvs
                ]
            finally:
                await client.aclose()
        elif cgm_source == "dexcom" and user_settings and user_settings.dexcom and user_settings.dexcom.username:
            dex = DexcomClient(
                username=user_settings.dexcom.username,
                password=user_settings.dexcom.password,
                region=user_settings.dexcom.region or "ous",
            )
            start_range = now_utc - timedelta(days=settings.night_pattern.days)
            cgm_entries = [
                (reading.date, float(reading.sgv))
                for reading in await dex.get_sgv_range(start_range, now_utc)
            ]

        pattern = None
        if cgm_entries:
            pattern = await get_or_compute_pattern(
                session=session,
                user_id=username,
                cfg=settings.night_pattern,
                source=cgm_source or "unknown",
                cgm_entries=cgm_entries,
                treatments=unique_rows,
            )

        if pattern:
            adjusted_series, meta_dict, adjustment = apply_night_pattern_adjustment(
                response.series,
                pattern,
                settings.night_pattern,
                now_local,
                context,
            )
            response.series = adjusted_series
            if response.baseline_series and adjustment != 0:
                response.baseline_series = [
                    ForecastPoint(t_min=point.t_min, bg=round(point.bg + adjustment, 1))
                    for point in response.baseline_series
                ]
            pattern_meta = NightPatternMeta(**meta_dict)
        else:
            pattern_meta.reason_not_applied = "Patrón no disponible"

        logger.info(
            "Night pattern evaluation",
            extra={
                "user_id": username,
                "pattern_enabled": settings.night_pattern.enabled,
                "pattern_applied": pattern_meta.applied,
                "pattern_reason": pattern_meta.reason_not_applied,
                "pattern_window": pattern_meta.window,
                "pattern_source": cgm_source,
            },
        )

    else:
        pattern_meta.reason_not_applied = "Desactivado por configuración"

    response.prediction_meta = PredictionMeta(pattern=pattern_meta)
    return response


@router.post("/simulate", response_model=ForecastResponse, summary="Simulate future glucose (Forecast)")
async def simulate_forecast(
    payload: ForecastSimulateRequest,
    user = Depends(get_current_user), # Require auth
    session: AsyncSession = Depends(get_db_session)
):
    """
    Run the Forecast Engine to predict glucose values over a horizon (defaults to 360m).
    Consider factors: IOB, COB, Basal Drift, Momentum.
    """
    try:
        # Auto-enrich with momentum if not provided and not explicitly disabled
        # We only do this if the user hasn't provided their own series
        if not payload.recent_bg_series and (not payload.momentum or payload.momentum.enabled):
             ns_config = await get_ns_config(session, user.username)
             if ns_config and ns_config.enabled and ns_config.url:
                try:
                    # Default/Ensure Momentum Config is ON
                    if not payload.momentum:
                        from app.models.forecast import MomentumConfig
                        payload.momentum = MomentumConfig(enabled=True, lookback_points=5)

                    client = NightscoutClient(ns_config.url, ns_config.api_secret)
                    
                    now_utc = datetime.now(timezone.utc)
                    start_search = now_utc - timedelta(minutes=45)
                    end_search = now_utc + timedelta(minutes=20)
                    
                    history_sgvs = await client.get_sgv_range(start_search, end_search, count=20)
                    if history_sgvs:
                        recent_series = []
                        history_sgvs.sort(key=lambda x: x.date, reverse=True)
                        
                        # Note: We do NOT override payload.start_bg here. 
                        # The user might be simulating a hypothetical start BG (e.g. "What if I was 100?").
                        # We just provide the "Trend Context" (Slope) from real history.
                        
                        for entry in history_sgvs:
                            entry_ts = entry.date / 1000.0
                            mins_ago = (now_utc.timestamp() - entry_ts) / 60.0
                            
                            if mins_ago < 0:
                                mins_ago = 0.0

                            if 0 <= mins_ago <= 60:
                                recent_series.append({
                                    "minutes_ago": mins_ago,
                                    "value": float(entry.sgv)
                                })
                        
                        payload.recent_bg_series = recent_series
                        
                    await client.aclose()
                except Exception as e:
                    print(f"Simulate NS Fetch warning: {e}")
                    # Continue without momentum
        
        # Auto-enrich with History (IOB/COB) from DB
        # We always do this to ensure IOB is accounted for, unless the client explicitly provided "history" events.
        # How to detect "history"? If payload events have negative offsets.
        # But even then, we might want to merge. 
        # Strategy: Fetch DB events. If an event from DB is NOT in payload (by timestamp/match), add it.
        # Since payload usually only contains the "Proposed" bolus (offset 0), we can just append past events.
        
        # Load User Settings (Always needed for context/fallbacks)
        user_settings = None
        try:
             from app.services.settings_service import get_user_settings_service
             from app.models.settings import UserSettings
             
             data = await get_user_settings_service(user.username, session)
             if data and data.get("settings"):
                 user_settings = UserSettings.migrate(data["settings"])
        except Exception:
             pass

        has_history = any(b.time_offset_min < -1 for b in payload.events.boluses)
        
        if not has_history:
             # user_settings already loaded above

             cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
             
             # Need to import Treatment model
             from app.models.treatment import Treatment
             from sqlalchemy import select
             
             stmt = (
                select(Treatment)
                .where(Treatment.user_id == user.username)
                .where(Treatment.created_at >= cutoff.replace(tzinfo=None))
                .order_by(Treatment.created_at.desc())
             )
             result = await session.execute(stmt)
             rows = result.scalars().all()
             
             # Deduplicate rows logic (reused from get_current or simplified)
             unique_rows = []
             if rows:
                 sorted_rows = sorted(rows, key=lambda x: x.created_at)
                 last_row = None
                 for row in sorted_rows:
                     is_dup = False
                     dt_diff = 999999 # Safety init
                     if last_row:
                         dt_diff = abs((row.created_at - last_row.created_at).total_seconds())
                         if dt_diff < 120:
                             if row.insulin == last_row.insulin and row.carbs == last_row.carbs:
                                 is_dup = True
                         elif abs(dt_diff - 3600) < 120 or abs(dt_diff - 7200) < 120:
                             if row.insulin == last_row.insulin and row.carbs == last_row.carbs:
                                 is_dup = True
                     
                     # Enhanced Deduplication Logic
                     r_ins = getattr(row, 'insulin', 0) or 0
                     l_ins = getattr(last_row, 'insulin', 0) or 0
                     r_carbs = getattr(row, 'carbs', 0) or 0
                     l_carbs = getattr(last_row, 'carbs', 0) or 0
                     
                     # Preserve macros if present in either (prefer the one we keep, usually 'row')
                     # Note: Deduplication logic below might discard 'row' or 'unique_rows.pop()'.
                     # The structure of ForecastEventCarbs creation later relies on 'rows' having these attrs.

                     
                     # 1. Carb Update Collision (Insulin=0 for both)
                     if not is_dup and r_ins == 0 and l_ins == 0:
                         if dt_diff < 300:
                             if r_carbs > l_carbs:
                                 unique_rows.pop()
                                 unique_rows.append(row)
                                 last_row = row
                                 is_dup = True
                             else:
                                 is_dup = True

                     # 2. Bolus Covering Carb Entry (Insulin > 0 covering Ins=0)
                     if not is_dup and l_ins == 0 and r_ins > 0 and r_carbs > 0:
                        if dt_diff < 900:
                             if abs(r_carbs - l_carbs) <= 10:
                                 unique_rows.pop()
                                 unique_rows.append(row)
                                 last_row = row
                                 is_dup = True
                     
                     # 3. Reverse (Bolus then Carb)
                     if not is_dup and l_ins > 0 and l_carbs > 0 and r_ins == 0:
                        if dt_diff < 900:
                            if abs(r_carbs - l_carbs) <= 10:
                                is_dup = True
                     
                     if not is_dup:
                         unique_rows.append(row)
                         last_row = row
                 rows = unique_rows

             # Default Params if settings fail (fallback to request params)
             p_icr = payload.params.icr
             p_absorption = payload.params.carb_absorption_minutes

             # Helper for Slot Resolution (Localized)
             def _resolve_hist_params(h: int, settings):
                if not settings: 
                    return p_icr, p_absorption
                    
                if 5 <= h < 11:
                    return settings.cr.breakfast, int(settings.absorption.breakfast)
                elif 11 <= h < 17:
                    return settings.cr.lunch, int(settings.absorption.lunch)
                elif 17 <= h < 23:
                    return settings.cr.dinner, int(settings.absorption.dinner)
                else:
                    return settings.cr.dinner, int(settings.absorption.dinner)

             # Identify rows that conflict/duplicate the Proposed Payload Carbs.
             # Scenario: User enters 15g Carbs manually (params.carbs_g), but there is an "Orphan" 15g Carbs from MyFitnessPal in history.
             # We should assume the manual entry COVERS the orphan, preventing double counting and ghost macros.
             
             skip_row_ids = set()
             
             # Check against the "Active Meal" proposed in params
             proposed_carbs = getattr(payload.params, 'carbs_g', 0)
             if proposed_carbs and proposed_carbs > 0:
                 for row in rows:
                     # Only check Carb-only entries (Orphans) that have no insulin associated
                     if (getattr(row, 'insulin', 0) or 0) == 0 and (row.carbs and row.carbs > 0):
                        r_time = row.created_at
                        if r_time.tzinfo is None: r_time = r_time.replace(tzinfo=timezone.utc)
                        r_diff_minutes = (datetime.now(timezone.utc) - r_time).total_seconds() / 60.0 # Positive minutes ago
                        
                        # Time check: If orphan is within 90 mins of "Now"
                        if r_diff_minutes < 90:
                            # Gram check: +/- 5g or +/- 15% tolerance
                            diff_g = abs(proposed_carbs - row.carbs)
                            if diff_g < 5.0 or diff_g < (proposed_carbs * 0.15):
                                # Collision detected. Prefer the Payload (User Intent).
                                skip_row_ids.add(id(row))
                                # We only dedup ONE orphan per proposed meal to be safe
                                break

             for row in rows:
                if id(row) in skip_row_ids:
                    continue
                    
                created_at = row.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                
                diff_min = (datetime.now(timezone.utc) - created_at).total_seconds() / 60.0
                offset = -1 * diff_min # Negative for past
                
                # Resolving User Hour for Settings
                user_hour = (created_at.hour + 1) % 24
                if user_settings and user_settings.timezone:
                    try:
                        from zoneinfo import ZoneInfo
                        tz = ZoneInfo(user_settings.timezone)
                        user_hour = created_at.astimezone(tz).hour
                    except Exception:
                        pass
                
                hist_icr, hist_abs = _resolve_hist_params(user_hour, user_settings)

                if row.insulin and row.insulin > 0:
                    dur = getattr(row, "duration", 0.0) or 0.0
                    payload.events.boluses.append(ForecastEventBolus(
                        time_offset_min=int(offset), 
                        units=row.insulin, 
                        duration_minutes=dur
                    ))
                    
                    # Split Logic (same as main forecast)
                    if dur <= 0 and row.notes:
                        import re
                        split_note_regex = re.compile(
                            r"split:\s*([0-9]+(?:\.[0-9]+)?)\s*now\s*\+\s*([0-9]+(?:\.[0-9]+)?)\s*delayed\s*([0-9]+)m",
                            re.IGNORECASE,
                        )
                        match = split_note_regex.search(row.notes or "")
                        if match:
                            try:
                                later_u = float(match.group(2))
                                delay_min = int(float(match.group(3)))
                                if later_u > 0 and delay_min >= 0:
                                    payload.events.boluses.append(ForecastEventBolus(
                                        time_offset_min=int(offset + delay_min),
                                        units=later_u,
                                        duration_minutes=dur
                                    ))
                            except Exception:
                                pass
                
                if row.carbs and row.carbs > 0:
                    payload.events.carbs.append(ForecastEventCarbs(
                        time_offset_min=int(offset), 
                        grams=row.carbs,
                        icr=float(hist_icr), 
                        absorption_minutes=hist_abs,
                        fat_g=getattr(row, 'fat', 0) or 0,
                        protein_g=getattr(row, 'protein', 0) or 0,
                        fiber_g=getattr(row, 'fiber', 0) or 0
                    ))

             # Basal fetching moved outside to ensure it runs even if history exists
             pass

        # 3. Fetch Basal History (Always try if missing from payload)
        if not payload.events.basal_injections:
             try:
                 from app.models.basal import BasalEntry
                 from sqlalchemy import select
                 
                 basal_cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
                 stmt_basal = (
                     select(BasalEntry)
                     .where(BasalEntry.user_id == user.username)
                     .where(BasalEntry.created_at >= basal_cutoff.replace(tzinfo=None))
                     .order_by(BasalEntry.created_at.desc())
                 )
                 result_basal = await session.execute(stmt_basal)
                 basal_rows = result_basal.scalars().all()
                 
                 for row in basal_rows:
                     b_created_at = row.created_at
                     if b_created_at.tzinfo is None:
                         b_created_at = b_created_at.replace(tzinfo=timezone.utc)
                     
                     b_diff_min = (datetime.now(timezone.utc) - b_created_at).total_seconds() / 60.0
                     b_offset = -1 * b_diff_min
                     dur = (row.effective_hours or 24) * 60
                     b_type = row.basal_type if row.basal_type else "glargine"
                     
                     # Simple Dedupe (Safety)
                     # Check if we already have this EXACT injection (time + units)
                     # to avoid double insertion if logic runs twice or parallel merge
                     # (Though we are inside 'if not basal_injections', so list is empty initially.
                     # But loop continues, so we dedupe against *just added* items? No need.)
                     
                     payload.events.basal_injections.append(ForecastBasalInjection(
                         time_offset_min=int(b_offset),
                         units=row.dose_u,
                         duration_minutes=dur,
                         type=b_type
                     ))
             except Exception as e:
                 print(f"Forecast Simulate Basal Error: {e}")
                 pass
        
        # GUARD: Ensure Basal Reference (Liver Compensation)
        # If we have basal injections (Active Insulin), we MUST have a matching 'basal_daily_units' (Reference).
        # Otherwise, the engine sees Active Insulin against 0 Reference (Liver=0) -> Hypo (Crash).
        # We calculate the daily total from the User Settings Schedule (The Reference) if the parameter is missing.
        # DO NOT SUM HISTORY (Injections != Reference).
        
        basal_daily_before = payload.params.basal_daily_units or 0.0
        
        if (payload.params.basal_daily_units or 0) < 0.1 and payload.events.basal_injections:
            # Try to fetch from User Settings Schedule
            ref_units = 0.0
            if user_settings and user_settings.bot and user_settings.bot.proactive and user_settings.bot.proactive.basal:
                 schedule = user_settings.bot.proactive.basal.schedule
                 if schedule:
                      ref_units = sum(item.units for item in schedule)
            
            # Fallback: TDD / 2
            if ref_units <= 0 and user_settings and user_settings.tdd_u:
                 ref_units = user_settings.tdd_u * 0.5
            
            # Fallback: Last Resort (Sum History but capped/averaged?) 
            # No, if we have no settings, we prefer 0 drift (Crash if active) or safe default?
            # If we set 0 here, it crashes. 
            # If we use the injection sum as last resort, it might Drift Up (as verified in thought process).
            # Drifting Up is safer than Crashing Down to 20.
            # So as absolute last fallback, we use the injection sum (normalized roughly).
            if ref_units <= 0:
                 ref_units = sum(b.units for b in payload.events.basal_injections if b.time_offset_min > -1440)
            
            payload.params.basal_daily_units = ref_units
            
        basal_daily_after = payload.params.basal_daily_units or 0.0

        # Debug Logging for Basal
        import os
        if os.environ.get("PREDICTION_DEBUG", "false").lower() == "true":
             try:
                 count_basal = len(payload.events.basal_injections)
                 print(f"DEBUG_FORECAST: basal_count={count_basal} daily_units_before={basal_daily_before:.2f} daily_units_after={basal_daily_after:.2f} has_history={has_history} start_bg={payload.start_bg}")
             except: pass

        # Apply Insulin Onset Delay (Physiological Lag)
        # Shifts all rapid boluses into the future by onset_min (e.g. 10m)
        # ONLY apply to "Current/Proposed" boluses (offset >= -1), not history.
        
        # 1. Determine Onset Value
        onset_val = 10 # Default
        
        if payload.params.insulin_onset_minutes is not None:
            # Trusted Source: Frontend
            onset_val = payload.params.insulin_onset_minutes
        elif user_settings and user_settings.insulin and user_settings.insulin.name:
            # Fallback: Backend Inference from Settings
            iname = (user_settings.insulin.name or "").lower()
            if "fiasp" in iname or "lyumjev" in iname:
                onset_val = 5
            elif any(x in iname for x in ["novorapid", "aspart", "humalog", "lispro", "apidra"]):
                onset_val = 15
        
        # 2. Apply Shift
        if onset_val > 0:
            for bolus in payload.events.boluses:
                if bolus.time_offset_min > 0:
                    bolus.time_offset_min += onset_val

        # Calculate Resistance Multiplier (If not provided) in /simulate
        # Uses ISF (Correction Factor) as reference
        if payload.params.insulin_sensitivity_multiplier is None and user_settings and user_settings.cf:
             try:
                 # Reference: Lunch ISF
                 isf_ref = float(user_settings.cf.lunch) if user_settings.cf.lunch else 0.0
                 
                 # Current Slot ISF (Simulated)
                 # In simulate endpoint, 'params.isf' is the effective ISF for the prediction
                 isf_slot = payload.params.isf
                 
                 if isf_ref > 0 and isf_slot > 0:
                     ratio = isf_slot / isf_ref
                     multiplier = max(0.4, min(1.2, ratio))
                     payload.params.insulin_sensitivity_multiplier = multiplier
             except Exception:
                 pass

        # Validate logic? (Pydantic does structure, Engine does math)
        response = ForecastEngine.calculate_forecast(payload)
        
        # --- Baseline Calculation (Ghost Line) ---
        # We calculate what would happen WITHOUT the "Proposed" events (offset >= -5).
        # This gives the user a visual comparison: "With Bolus" vs "Do Nothing".
        try:
            from copy import deepcopy
            payload_base = deepcopy(payload)
            
            # Filter: Keep ONLY history (older than 5 mins ago)
            # This removes the "Current/Proposed" bolus and carbs.
            base_boluses = [b for b in payload_base.events.boluses if b.time_offset_min < -5]
            base_carbs = [c for c in payload_base.events.carbs if c.time_offset_min < -5]
             
            # Only strictly necessary if we actually removed something
            if len(base_boluses) != len(payload.events.boluses) or len(base_carbs) != len(payload.events.carbs):
                 payload_base.events.boluses = base_boluses
                 payload_base.events.carbs = base_carbs
                 
                 # Recalculate
                 resp_base = ForecastEngine.calculate_forecast(payload_base)
                 response.baseline_series = resp_base.series
        except Exception as ex:
            print(f"Baseline calc warning: {ex}")

        if not payload.events.boluses and not payload.events.carbs:
            response.quality = "low"
            response.warnings.append("Sin eventos históricos; pronóstico incompleto por falta de IOB/COB.")
        return response
    except Exception as e:
        # Log error in real app
        print(f"Forecast Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
