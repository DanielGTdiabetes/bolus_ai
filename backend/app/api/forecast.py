from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from app.models.forecast import ForecastSimulateRequest, ForecastResponse, ForecastEvents, ForecastEventBolus, ForecastEventCarbs, SimulationParams
from app.services.forecast_engine import ForecastEngine
from app.core.security import get_current_user, CurrentUser
from app.core.db import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.settings_service import get_user_settings_service
from app.models.settings import UserSettings
from app.services.nightscout_secrets_service import get_ns_config
from app.services.nightscout_client import NightscoutClient
from app.services.autosens_service import AutosensService

router = APIRouter()

@router.get("/current", response_model=ForecastResponse, summary="Get ambient forecast based on current status")
async def get_current_forecast(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    start_bg_param: Optional[float] = Query(None, alias="start_bg", description="Override start BG if known by client"),
    future_insulin_u: Optional[float] = Query(None, description="Future planned insulin units (e.g. dual bolus remainder)"),
    future_insulin_delay_min: Optional[int] = Query(0, description="Delay in minutes for future insulin")
):
    """
    Auto-generates a forecast based on:
    - Current BG (from Nightscout)
    - Active IOB/COB (from DB Treatments)
    - User Settings (ISF/ICR)
    """
    # 1. Load Settings
    user_settings = None
    try:
        data = await get_user_settings_service(user.username, session)
        if data and data.get("settings"):
            user_settings = UserSettings.migrate(data["settings"])
    except Exception:
        pass
        
    if not user_settings:
        raise HTTPException(status_code=400, detail="Settings not found")

    # 2. Fetch Current BG & History (NS)
    ns_config = await get_ns_config(session, user.username)
    # Default fallback or explicit override
    start_bg = start_bg_param if start_bg_param is not None else 120.0
    
    recent_bg_series = []
    
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

    # 3. Fetch Treatments (Last 6 hours)
    from app.models.treatment import Treatment
    from sqlalchemy import select
    from datetime import datetime, timedelta, timezone
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    
    # 3.0 Fetch DB Treatments
    stmt = (
        select(Treatment)
        .where(Treatment.user_id == user.username)
        .where(Treatment.created_at >= cutoff.replace(tzinfo=None)) # DB assumes naive usually
        .order_by(Treatment.created_at.desc())
    )
    result = await session.execute(stmt)
    db_rows = result.scalars().all()

    # 3.1 Fetch NS Treatments (External Data)
    ns_rows = []
    if ns_config and ns_config.enabled and ns_config.url:
        try:
            client = NightscoutClient(ns_config.url, ns_config.api_secret, timeout_seconds=5)
            # Fetch last 6 hours
            ns_treatments = await client.get_recent_treatments(hours=6, limit=200)
            await client.aclose()
            
            # Convert NS treatments to pseudo-Treatment objects for uniform processing
            for t in ns_treatments:
                # Map fields
                _id = t.id or t._id
                _created_at = t.created_at
                _insulin = t.insulin
                _carbs = t.carbs
                _notes = t.notes
                _duration = t.duration
                
                # Filter out obvious duplicates already in DB? 
                # We do dedupe below, so just append.
                # Create a simple object or dict accessor wrapper
                class PseudoTreatment:
                    def __init__(self, id, created_at, insulin, carbs, notes, duration):
                        self.id = id
                        self.created_at = created_at
                        self.insulin = insulin
                        self.carbs = carbs
                        self.notes = notes
                        self.duration = duration
                
                # Check formatting
                if isinstance(_created_at, str):
                    try:
                        _created_at = datetime.fromisoformat(_created_at.replace("Z", "+00:00"))
                    except:
                        pass
                
                # Ensure UTC
                if isinstance(_created_at, datetime) and _created_at.tzinfo is None:
                    _created_at = _created_at.replace(tzinfo=timezone.utc)
                
                ns_rows.append(PseudoTreatment(_id, _created_at, _insulin, _carbs, _notes, _duration))
                
        except Exception as e:
            print(f"Forecast NS Treatment fetch failed: {e}")
            pass

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
                     if dt_diff < 300: # Within 5 minutes
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
            
            if not is_dup:
                unique_rows.append(row)
                last_row = row
        
    rows = unique_rows

    boluses = []
    carbs = []
    
    now_utc = datetime.now(timezone.utc)
    
    # Helper to resolve slot
    def get_slot_params(h: int, settings: UserSettings):
        # Default to Lunch if unknown
        icr = settings.cr.lunch
        isf = settings.cf.lunch
        absorption = settings.absorption.lunch
        
        # Simple Logic (assuming User Time)
        # Breakfast: 05:00 - 11:00
        # Lunch: 11:00 - 17:00
        # Dinner: 17:00 - 23:00 (or later)
        
        if 5 <= h < 11:
            icr = settings.cr.breakfast
            isf = settings.cf.breakfast
            absorption = settings.absorption.breakfast
        elif 11 <= h < 17:
             icr = settings.cr.lunch
             isf = settings.cf.lunch
             absorption = settings.absorption.lunch
        elif 17 <= h < 23:
             icr = settings.cr.dinner
             isf = settings.cf.dinner
             absorption = settings.absorption.dinner
        else:
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
        
        # Determine Hour in User Time (Approx UTC+1 for Daniel/Spain)
        # Ideally we store timezone in user settings
        user_hour = (created_at.hour + 1) % 24 
        
        if row.insulin and row.insulin > 0:
            dur = getattr(row, "duration", 0.0) or 0.0
            boluses.append(ForecastEventBolus(
                time_offset_min=int(offset), 
                units=row.insulin,
                duration_minutes=dur
            ))
            
        if row.carbs and row.carbs > 0:
            # Resolve ICR for this SPECIFIC event time
            evt_icr, _, evt_abs = get_slot_params(user_hour, user_settings)
            
            # Alcohol Check
            if row.notes and "alcohol" in row.notes.lower():
                evt_abs = 480 # 8 hours for alcohol
            
            # Dual Bolus Check (Persistent Memory)
            # If the notes say "Dual", it's a slow meal (Pizza/Fat), so we use 6h absorption.
            # This ensures correctness even after the "Active Plan" finishes.
            elif row.notes and "dual" in row.notes.lower():
                evt_abs = 360

            carbs.append(ForecastEventCarbs(
                time_offset_min=int(offset), 
                grams=row.carbs,
                icr=evt_icr,
                absorption_minutes=evt_abs
            ))



    
    # Initialize current parameters for the simulation
    now_hour = (datetime.now(timezone.utc).hour + 1) % 24
    curr_icr, curr_isf, _ = get_slot_params(now_hour, user_settings)

    # 3.4 Calculate Autosens (if enabled)
    # We do this logic right before constructing final simulation params
    autosens_ratio = 1.0
    if user_settings.autosens.enabled:
         try:
             # We need to await it. Service is async.
             res = await AutosensService.calculate_autosens(user.username, session, user_settings)
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
        boluses.append(ForecastEventBolus(time_offset_min=future_insulin_delay_min, units=future_insulin_u))
        
        # SMART ADJUSTMENT:
        # If there is a dual bolus active, it implies the meal is slow/complex (Pizza/Fat).
        # Standard absorption (e.g. 3h) will predict a massive spike because only 70% insulin was given.
        # We must extend the consumption curve of the recent meal to match the "Dual" strategy.
        # Strategy: Find the recent large meal and force its absorption to at least 6 hours (360 min).
        for c in carbs:
            # If carbs > 20g and happened in the last 60 mins
            if c.grams > 20 and c.time_offset_min > -60:
                # Use MAX to avoid overwriting Alcohol (480) or other stronger settings
                c.absorption_minutes = max(getattr(c, 'absorption_minutes', 0), 360)

    # 4. Construct Request
    # Current params
    now_user_hour = (now_utc.hour + 1) % 24
    curr_icr, curr_isf, curr_abs = get_slot_params(now_user_hour, user_settings)
    
    # Check Sick Mode (Resistance)
    try:
        sick_stmt = (
            select(Treatment)
            .where(Treatment.user_id == user.username)
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

    sim_params = SimulationParams(
        isf=curr_isf,
        icr=curr_icr, 
        dia_minutes=int(user_settings.iob.dia_hours * 60),
        carb_absorption_minutes=curr_abs,
        insulin_peak_minutes=user_settings.iob.peak_minutes,
        insulin_model=user_settings.iob.curve
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

    payload = ForecastSimulateRequest(
        start_bg=start_bg,
        params=sim_params,
        events=ForecastEvents(boluses=boluses, carbs=carbs),
        momentum=MomentumConfig(enabled=use_momentum, lookback_points=5),
        recent_bg_series=recent_bg_series if recent_bg_series else None
    )
    
    response = ForecastEngine.calculate_forecast(payload)
    
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
        
        has_history = any(b.time_offset_min < -1 for b in payload.events.boluses)
        
        if not has_history:
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
             # We'll use the timezone-aware dedupe logic inline or reused.
             # For simulation, slight duplications are less critical than missing IOB, 
             # but we should try to avoid the "Double Phantom" issue.
             
             unique_rows = []
             if rows:
                 sorted_rows = sorted(rows, key=lambda x: x.created_at)
                 last_row = None
                 for row in sorted_rows:
                     is_dup = False
                     if last_row:
                         dt_diff = abs((row.created_at - last_row.created_at).total_seconds())
                         # Standard 2 min check
                         if dt_diff < 120:
                             if row.insulin == last_row.insulin and row.carbs == last_row.carbs:
                                 is_dup = True
                         # Timezone 1h check
                         elif abs(dt_diff - 3600) < 120 or abs(dt_diff - 7200) < 120:
                             if row.insulin == last_row.insulin and row.carbs == last_row.carbs:
                                 is_dup = True
                     
                     if not is_dup:
                         unique_rows.append(row)
                         last_row = row
                 rows = unique_rows

             # Params for COB (Approximate from payload or defaults)
             p_icr = payload.params.icr
             p_absorption = payload.params.carb_absorption_minutes
             
             for row in rows:
                created_at = row.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                
                diff_min = (datetime.now(timezone.utc) - created_at).total_seconds() / 60.0
                offset = -1 * diff_min # Negative for past
                
                # We skip future DB events (shouldn't happen) or very recent ones that might clash with "Proposed"?
                # Actually proposed is usually "New". Using offset 0.
                # If DB has something at offset -1 min, it's history.
                
                if row.insulin and row.insulin > 0:
                    dur = getattr(row, "duration", 0.0) or 0.0
                    payload.events.boluses.append(ForecastEventBolus(
                        time_offset_min=int(offset), 
                        units=row.insulin, 
                        duration_minutes=dur
                    ))
                
                if row.carbs and row.carbs > 0:
                    payload.events.carbs.append(ForecastEventCarbs(
                        time_offset_min=int(offset), 
                        grams=row.carbs,
                        icr=p_icr, 
                        absorption_minutes=p_absorption 
                    ))

        # Validate logic? (Pydantic does structure, Engine does math)
        response = ForecastEngine.calculate_forecast(payload)
        return response
    except Exception as e:
        # Log error in real app
        print(f"Forecast Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
