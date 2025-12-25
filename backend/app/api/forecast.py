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
    
    stmt = (
        select(Treatment)
        .where(Treatment.user_id == user.username)
        .where(Treatment.created_at >= cutoff.replace(tzinfo=None)) # DB assumes naive usually
        .order_by(Treatment.created_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    
    # 3.1 Deduplicate Rows (Fix for Double Submission / Echoes)
    # We filter out events that are extremely close in time with identical values.
    unique_rows = []
    if rows:
        # Sort by created_at to ensure proximity
        sorted_rows = sorted(rows, key=lambda x: x.created_at)
        
        last_row = None
        for row in sorted_rows:
            is_dup = False
            if last_row:
                dt_diff = abs((row.created_at - last_row.created_at).total_seconds())
                # If within 2 mins and identical values
                if dt_diff < 120:
                    same_ins = (row.insulin == last_row.insulin)
                    same_carbs = (row.carbs == last_row.carbs)
                    if same_ins and same_carbs:
                        is_dup = True
            
            if not is_dup:
                unique_rows.append(row)
                last_row = row
        
        # Use refined list
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
        
        if not payload.events.boluses and not payload.events.carbs:
             # Auto-enrich with History (IOB/COB) if payload events are empty (Stateless call)
             # This ensures we account for IOB even if frontend didn't pass it.
             # We fetch last 6 hours of treatments.
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
             
             # Helper for Slot Params (We reuse the logic from get_current_forecast if possible, 
             # but here we might just use current params for simplicity or simple defaults.
             # Ideally we should pick params based on event time. 
             # For robustness, we will simpler mapping or use the passed params as fallback.)
             
             # Actually, simpler: Load UserSettings once.
             # We can't easily reuse get_slot_params without refactoring.
             # We'll use the 'params' passed in payload as the "Current Profile" 
             # and assume recent history follows roughly similar physics or just use ICR/ISF from payload.
             # This is an approximation but better than 0 history.
             
             p_icr = payload.params.icr
             p_absorption = payload.params.carb_absorption_minutes
             
             for row in rows:
                created_at = row.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                
                diff_min = (datetime.now(timezone.utc) - created_at).total_seconds() / 60.0
                offset = -1 * diff_min # Negative for past
                
                if row.insulin and row.insulin > 0:
                    payload.events.boluses.append(ForecastEventBolus(time_offset_min=int(offset), units=row.insulin))
                
                if row.carbs and row.carbs > 0:
                    payload.events.carbs.append(ForecastEventCarbs(
                        time_offset_min=int(offset), 
                        grams=row.carbs,
                        icr=p_icr, # Approximate
                        absorption_minutes=p_absorption # Approximate
                    ))

        # Validate logic? (Pydantic does structure, Engine does math)
        response = ForecastEngine.calculate_forecast(payload)
        return response
    except Exception as e:
        # Log error in real app
        print(f"Forecast Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
