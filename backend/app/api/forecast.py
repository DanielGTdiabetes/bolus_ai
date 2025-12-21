from fastapi import APIRouter, Depends, HTTPException
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
    session: AsyncSession = Depends(get_db_session)
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

    # 2. Fetch Current BG (NS)
    ns_config = await get_ns_config(session, user.username)
    start_bg = 120.0 # Default fallback
    recent_bg = []
    
    if ns_config and ns_config.enabled and ns_config.url:
        try:
            client = NightscoutClient(ns_config.url, ns_config.api_secret)
            sgv = await client.get_latest_sgv()
            start_bg = float(sgv.sgv)
            await client.aclose()
            # TODO: Fetch recent history for momentum?
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
    
    boluses = []
    carbs = []
    
    now_utc = datetime.now(timezone.utc)
    
    # Helper to resolve slot
    def get_slot_params(h: int, settings: UserSettings):
        # Default to Lunch if unknown
        icr = settings.cr.lunch
        isf = settings.cf.lunch
        
        # Simple Logic (assuming User Time)
        # Breakfast: 05:00 - 11:00
        # Lunch: 11:00 - 17:00
        # Dinner: 17:00 - 23:00 (or later)
        
        if 5 <= h < 11:
            icr = settings.cr.breakfast
            isf = settings.cf.breakfast
        elif 11 <= h < 17:
             icr = settings.cr.lunch
             isf = settings.cf.lunch
        elif 17 <= h < 23:
             icr = settings.cr.dinner
             isf = settings.cf.dinner
        
        # Fallback for night owls (23-05) -> Dinner or specific?
        # Usually dinner settings persist, or we wrap to breakfast.
        # Let's assume Dinner for late night snacking for now.
        else:
             icr = settings.cr.dinner
             isf = settings.cf.dinner
             
        return float(icr), float(isf)

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
            boluses.append(ForecastEventBolus(time_offset_min=int(offset), units=row.insulin))
            
        if row.carbs and row.carbs > 0:
            # Resolve ICR for this SPECIFIC event time
            evt_icr, _ = get_slot_params(user_hour, user_settings)
            
            carbs.append(ForecastEventCarbs(
                time_offset_min=int(offset), 
                grams=row.carbs,
                icr=evt_icr
            ))

    # 4. Construct Request
    # Current params
    now_user_hour = (now_utc.hour + 1) % 24
    curr_icr, curr_isf = get_slot_params(now_user_hour, user_settings)
    
    # Calculate dynamic absorption based on recent carbs quantity
    total_recent_carbs = 0
    for c in carbs:
        # Check if carb is recent (e.g. last 90 mins)
        # c.time_offset_min is negative (e.g. -10)
        if c.time_offset_min > -90:
            total_recent_carbs += c.grams
            
    dynamic_absorption = 180 # Default fallback
    if total_recent_carbs > 0:
        if total_recent_carbs < 20: 
            dynamic_absorption = 100 # Fast for snacks
        elif total_recent_carbs < 50:
            dynamic_absorption = 150 # Medium
        else:
             dynamic_absorption = 210 # Slow for big meals

    sim_params = SimulationParams(
        isf=curr_isf,
        icr=curr_icr, 
        dia_minutes=int(user_settings.iob.dia_hours * 60),
        carb_absorption_minutes=dynamic_absorption,
        insulin_peak_minutes=user_settings.iob.peak_minutes
    )
    
    payload = ForecastSimulateRequest(
        start_bg=start_bg,
        params=sim_params,
        events=ForecastEvents(boluses=boluses, carbs=carbs),
        momentum=None # Skip for now to keep simple
    )
    
    return ForecastEngine.calculate_forecast(payload)


@router.post("/simulate", response_model=ForecastResponse, summary="Simulate future glucose (Forecast)")

async def simulate_forecast(
    payload: ForecastSimulateRequest,
    user = Depends(get_current_user) # Require auth
):
    """
    Run the Forecast Engine to predict glucose values over a horizon (defaults to 360m).
    Consider factors: IOB, COB, Basal Drift, Momentum.
    """
    try:
        # Validate logic? (Pydantic does structure, Engine does math)
        response = ForecastEngine.calculate_forecast(payload)
        return response
    except Exception as e:
        # Log error in real app
        print(f"Forecast Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
