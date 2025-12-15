from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.security import get_current_user
from app.core.settings import Settings, get_settings
from app.models.settings import UserSettings
from app.models.schemas import NightscoutSGV

from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2, GlucoseUsed
from app.models.bolus_split import (
    BolusPlanRequest, BolusPlanResponse, 
    RecalcSecondRequest, RecalcSecondResponse
)
from app.services.bolus_engine import calculate_bolus_v2
from app.services.bolus_split import create_plan, recalc_second

from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.services.nightscout_client import NightscoutClient, NightscoutError
from app.services.store import DataStore

logger = logging.getLogger(__name__)

router = APIRouter()


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))

@router.post("/plan", response_model=BolusPlanResponse, summary="Create a split bolus plan")
async def api_create_plan(payload: BolusPlanRequest):
    return create_plan(payload)

@router.post("/recalc-second", response_model=RecalcSecondResponse, summary="Recalculate second tranche")
async def api_recalc_second(payload: RecalcSecondRequest):
    return await recalc_second(payload)

@router.post("/calc", response_model=BolusResponseV2, summary="Calculate bolus (Stateless V2)")
async def calculate_bolus_stateless(
    payload: BolusRequestV2,
    store: DataStore = Depends(_data_store),
):
    # 1. Resolve Settings
    # If payload has settings, construct a temporary UserSettings object to satisfy the engine interface
    # Otherwise load from store (Legacy mode)
    
    if payload.settings:
        # Construct UserSettings adaptor from payload
        # This allows reusing existing engine logic without rewriting it all
        from app.models.settings import MealFactors, TargetRange, IOBConfig, NightscoutConfig
        
        # We map meal slots to the structure UserSettings expects
        cr_settings = MealFactors(
            breakfast=payload.settings.breakfast.icr,
            lunch=payload.settings.lunch.icr,
            dinner=payload.settings.dinner.icr
        )
        isf_settings = MealFactors(
            breakfast=payload.settings.breakfast.isf,
            lunch=payload.settings.lunch.isf,
            dinner=payload.settings.dinner.isf
        )
        
        target_settings = TargetRange(low=70, mid=100, high=180)
        
        iob_settings = IOBConfig(
             dia_hours=payload.settings.dia_hours,
             curve="bilinear", 
             peak_minutes=75 
        )
        
        # NS from payload
        ns_settings = NightscoutConfig(
            enabled=bool(payload.nightscout and payload.nightscout.url),
            url=payload.nightscout.url if payload.nightscout else "",
            token=payload.nightscout.token if payload.nightscout else ""
        )
        
        user_settings = UserSettings(
            cr=cr_settings,
            cf=isf_settings,
            targets=target_settings,
            iob=iob_settings,
            nightscout=ns_settings,
            max_bolus_u=payload.settings.max_bolus_u,
            max_correction_u=payload.settings.max_correction_u,
            round_step_u=payload.settings.round_step_u
        )
        
        if payload.target_mgdl is None:
             slot_profile = getattr(payload.settings, payload.meal_slot)
             payload.target_mgdl = slot_profile.target

    elif payload.cr_g_per_u:
        # Flat Overrides (Hybrid)
        from app.models.settings import MealFactors, TargetRange, IOBConfig, NightscoutConfig
        
        # Apply single CR/ISF to ALL slots for safety/simplicity in this stateless request
        cr_val = payload.cr_g_per_u
        isf_val = payload.isf_mgdl_per_u or 30.0
        
        cr_settings = MealFactors(breakfast=cr_val, lunch=cr_val, dinner=cr_val)
        isf_settings = MealFactors(breakfast=isf_val, lunch=isf_val, dinner=isf_val)
        
        target_settings = TargetRange(low=70, mid=payload.target_mgdl or 100, high=180)
        
        iob_settings = IOBConfig(
             dia_hours=payload.dia_hours or 4.0,
             curve="bilinear", 
             peak_minutes=75
        )
        
        ns_settings = NightscoutConfig(
            enabled=bool(payload.nightscout and payload.nightscout.url),
            url=payload.nightscout.url if payload.nightscout else "",
            token=payload.nightscout.token if payload.nightscout else ""
        )
        
        user_settings = UserSettings(
            cr=cr_settings,
            cf=isf_settings,
            targets=target_settings,
            iob=iob_settings,
            nightscout=ns_settings,
            max_bolus_u=payload.max_bolus_u or 10.0,
            max_correction_u=payload.max_correction_u or 5.0,
            round_step_u=payload.round_step_u or 0.05
        )

    else:
        # Legacy: Load from DB
        user_settings = store.load_settings()


    # 2. Resolve Nightscout Client
    ns_client: Optional[NightscoutClient] = None
    ns_config = user_settings.nightscout
    
    # If payload has explicit NS config, use it (override)
    if payload.nightscout:
        ns_config.enabled = True
        ns_config.url = payload.nightscout.url
        ns_config.token = payload.nightscout.token

    # 3. Resolve Glucose (Manual vs Nightscout)
    resolved_bg: Optional[float] = payload.bg_mgdl
    bg_source: Literal["manual", "nightscout", "none"] = "manual" if resolved_bg is not None else "none"
    bg_trend: Optional[str] = None
    bg_age_minutes: Optional[float] = None
    bg_is_stale: bool = False
    
    # Priority: Manual > Nightscout 
    if resolved_bg is None and ns_config.enabled and ns_config.url:
         logger.info(f"Attempting to fetch BG from Nightscout: {ns_config.url}")
         try:
            ns_client = NightscoutClient(
                base_url=ns_config.url,
                token=ns_config.token,
                timeout_seconds=5
            )
            sgv: NightscoutSGV = await ns_client.get_latest_sgv()
            
            resolved_bg = float(sgv.sgv)
            bg_source = "nightscout"
            bg_trend = sgv.direction
            
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            diff_ms = now_ms - sgv.date
            diff_min = diff_ms / 60000.0
            
            bg_age_minutes = diff_min
            if diff_min > 10: 
                 bg_is_stale = True
            
            logger.info(f"Nightscout fetch success: {resolved_bg} mg/dL, age={diff_min:.1f}m")

         except Exception as e:
            logger.error(f"Nightscout fetch failed in calc: {e}")
            bg_source = "none"
            pass 

    # 4. Calculate IOB
    # Ensure client exists if needed for IOB even if BG was manual
    if ns_client is None and ns_config.enabled and ns_config.url:
         ns_client = NightscoutClient(
            base_url=ns_config.url,
            token=ns_config.token,
            timeout_seconds=5
         )

    try:
        now = datetime.now(timezone.utc)
        iob_u, breakdown, iob_info, iob_warning = await compute_iob_from_sources(now, user_settings, ns_client, store)
        
        # 5. Call Engine
        glucose_info = GlucoseUsed(
            mgdl=resolved_bg,
            source=bg_source,
            trend=bg_trend,
            age_minutes=bg_age_minutes,
            is_stale=bg_is_stale
        )
        
        response = calculate_bolus_v2(
            request=payload,
            settings=user_settings,
            iob_u=iob_u,
            glucose_info=glucose_info
        )

        # Inject IOB Info
        response.iob = iob_info

        if iob_warning:
            response.warnings.append(iob_warning)
        
        if breakdown:
             response.explain.append(f"   (IOB basado en {len(breakdown)} tratamientos recientes)")
        
        return response

    finally:
        if ns_client:
            await ns_client.aclose()


class BolusAcceptRequest(BaseModel):
    insulin: float
    carbs: float = 0
    created_at: str
    notes: Optional[str] = ""
    enteredBy: str = "BolusAI"
    nightscout: Optional[dict] = None  # {url, token}


@router.post("/treatments", summary="Save a treatment (bolus) to NS/Local")
async def save_treatment(
    payload: BolusAcceptRequest,
    _: dict = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
):
    # 1. Save locally (Always, as backup/primary)
    treatment_data = {
        "eventType": "Correction Bolus" if payload.carbs == 0 else "Meal Bolus",
        "created_at": payload.created_at,
        "insulin": payload.insulin,
        "carbs": payload.carbs,
        "notes": payload.notes,
        "enteredBy": payload.enteredBy,
        "type": "bolus",
        "ts": payload.created_at, # Local store format
        "units": payload.insulin   # Local store format
    }
    
    events = store.load_events()
    events.append(treatment_data)
    # Keep last 1000?
    if len(events) > 1000:
        events = events[-1000:]
    store.save_events(events)
    
    # 2. Upload to Nightscout if configured
    ns_uploaded = False
    error = None
    
    # Check payload config first, then stored settings
    ns_url = payload.nightscout.get("url") if payload.nightscout else None
    ns_token = payload.nightscout.get("token") if payload.nightscout else None
    
    if not ns_url:
        settings = store.load_settings()
        if settings.nightscout.enabled:
            ns_url = settings.nightscout.url
            ns_token = settings.nightscout.token

    if ns_url:
        try:
            client = NightscoutClient(ns_url, ns_token, timeout_seconds=5)
            # NS expects specific format
            ns_payload = {
                "eventType": treatment_data["eventType"],
                "created_at": payload.created_at,
                "insulin": payload.insulin,
                "carbs": payload.carbs,
                "notes": payload.notes,
                "enteredBy": payload.enteredBy,
            }
            # Remove unused keys or just send
            await client.upload_treatments([ns_payload])
            await client.aclose()
            ns_uploaded = True
        except Exception as e:
            logger.error(f"Failed to upload treatment to NS: {e}")
            error = str(e)
            
    return {
        "success": True, 
        "local_saved": True, 
        "nightscout_uploaded": ns_uploaded,
        "nightscout_error": error
    }


@router.get("/iob", summary="Get current IOB and decay curve")
async def get_current_iob(
    store: DataStore = Depends(_data_store),
):
    # Construct settings or load
    settings = store.load_settings()
    
    # NS Client
    ns_client = None
    eff_url = settings.nightscout.url if settings.nightscout.enabled else None
    eff_token = settings.nightscout.token
    
    if eff_url:
        ns_client = NightscoutClient(eff_url, eff_token, timeout_seconds=5)
        
    try:
        now = datetime.now(timezone.utc)
        total_iob, breakdown, iob_info, iob_warning = await compute_iob_from_sources(now, settings, ns_client, store)
        
        # Calculate Curve for next 4 hours (every 10 min)
        # We reused "insulin_activity_fraction" from iob.py? No it's internal.
        # We should expose it or re-implement simply here for the graph points.
        # Actually iob calculations are complex over multiple boluses.
        # Ideally we simulate time forward.
        
        from app.services.iob import InsulinActionProfile, compute_iob
        
        profile = InsulinActionProfile(
            dia_hours=settings.iob.dia_hours,
            curve=settings.iob.curve,
            peak_minutes=settings.iob.peak_minutes
        )
        
        # Convert breakdown back to simple bolus list for simulation
        # breakdown has {ts(iso), units, iob(contribution)}
        # We need original units/ts to project forward.
        # Fortunately breakdown has 'units' and 'ts' (original time).
        
        active_boluses = []
        for b in breakdown:
            active_boluses.append({"ts": b["ts"], "units": b["units"]})
            
        curve_points = []
        from datetime import timedelta
        
        # 4 hours forward
        for i in range(0, 241, 10): # 0 to 240 min
            future_time = now + timedelta(minutes=i)
            val = compute_iob(future_time, active_boluses, profile)
            curve_points.append({
                "min_from_now": i,
                "iob": round(val, 2),
                "time": future_time.isoformat()
            })
            
            
        # Calculate COB
        total_cob = await compute_cob_from_sources(now, ns_client, store)

        return {
            "iob_total": round(total_iob, 2),
            "cob_total": round(total_cob, 0),
            "breakdown": breakdown, # Top contributors
            "graph": curve_points,
            "iob_info": iob_info.model_dump(),
            "warning": iob_warning
        }
        
    finally:
        if ns_client:
            await ns_client.aclose()
