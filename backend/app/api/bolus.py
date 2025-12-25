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
from app.core.db import get_db_session
from app.services.nightscout_secrets_service import get_ns_config
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter()


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))

@router.post("/plan", response_model=BolusPlanResponse, summary="Create a split bolus plan")
async def api_create_plan(payload: BolusPlanRequest):
    return create_plan(payload)

@router.post("/recalc-second", response_model=RecalcSecondResponse, summary="Recalculate second tranche")
async def api_recalc_second(
    payload: RecalcSecondRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    # Inject NS Config from DB if missing in payload
    if not payload.nightscout or not payload.nightscout.url:
        try:
            db_ns_config = await get_ns_config(session, user.username)
            if db_ns_config and db_ns_config.enabled and db_ns_config.url:
                # Create default dict if None
                if payload.nightscout is None:
                    # We need to assign a structure that matches the Pydantic model
                    # RecalcSecondRequest.nightscout is likely a model or dict. 
                    # Checking imports... it uses NightscoutConfig probably.
                    # Let's check RecalcSecondRequest definition if possible, but 
                    # usually it expects an object. 
                    # We can assign the fields directly if payload is a Pydantic model.
                    from app.models.settings import NightscoutConfig
                    payload.nightscout = NightscoutConfig(
                        url=db_ns_config.url,
                        token=db_ns_config.api_secret,
                        enabled=True
                    )
                else:
                    payload.nightscout.url = db_ns_config.url
                    payload.nightscout.token = db_ns_config.api_secret
                    payload.nightscout.enabled = True
        except Exception as e:
            logger.warning(f"Failed to inject NS config for recalc: {e}")

    return await recalc_second(payload)

@router.post("/calc", response_model=BolusResponseV2, summary="Calculate bolus (Stateless V2)")
async def calculate_bolus_stateless(
    payload: BolusRequestV2,
    store: DataStore = Depends(_data_store),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    # 1. Resolve Settings
    # If payload has settings, construct a temporary UserSettings object to satisfy the engine interface
    # Otherwise load from store (Legacy mode)
    
    if payload.settings:
        # Construct UserSettings adaptor from payload
        # This allows reusing existing engine logic without rewriting it all
        from app.models.settings import MealFactors, CorrectionFactors, TargetRange, IOBConfig, NightscoutConfig
        
        # We map meal slots to the structure UserSettings expects
        cr_settings = MealFactors(
            breakfast=payload.settings.breakfast.icr,
            lunch=payload.settings.lunch.icr,
            dinner=payload.settings.dinner.icr,
            snack=payload.settings.snack.icr if payload.settings.snack else 10.0
        )
        isf_settings = CorrectionFactors(
            breakfast=payload.settings.breakfast.isf,
            lunch=payload.settings.lunch.isf,
            dinner=payload.settings.dinner.isf,
            snack=payload.settings.snack.isf if payload.settings.snack else 30.0
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
        from app.models.settings import MealFactors, CorrectionFactors, TargetRange, IOBConfig, NightscoutConfig
        
        # Apply single CR/ISF to ALL slots for safety/simplicity in this stateless request
        cr_val = payload.cr_g_per_u
        isf_val = payload.isf_mgdl_per_u or 30.0
        
        cr_settings = MealFactors(breakfast=cr_val, lunch=cr_val, dinner=cr_val)
        isf_settings = CorrectionFactors(breakfast=isf_val, lunch=isf_val, dinner=isf_val)
        
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
        # Legacy: Load from DB if available, fallback to Store
        from app.services.settings_service import get_user_settings_service
        
        user_settings = None
        if session:
            try:
                data = await get_user_settings_service(user.username, session)
                if data and data.get("settings"):
                    user_settings = UserSettings.migrate(data["settings"])
            except Exception as e:
                logger.warning(f"Failed to load settings from DB for bolus: {e}")
                
        if not user_settings:
            user_settings = store.load_settings()


    # 2. Resolve Nightscout Client
    ns_client: Optional[NightscoutClient] = None
    ns_config = user_settings.nightscout
    
    # If payload has explicit NS config, use it (override)
    if payload.nightscout:
        ns_config.enabled = True
        ns_config.url = payload.nightscout.url
        ns_config.token = payload.nightscout.token
    elif session:
        # Check DB secrets if not overridden and available
        try:
            db_ns_config = await get_ns_config(session, user.username)
            if db_ns_config and db_ns_config.enabled and db_ns_config.url:
                ns_config.enabled = True
                ns_config.url = db_ns_config.url
                # Map api_secret to token for internal client usage
                ns_config.token = db_ns_config.api_secret 
                logger.debug("Injected Nightscout config from DB for calculation.")
        except Exception as e:
            logger.warning(f"Failed to fetch NS config from DB: {e}")

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

    # Load DB treatments for IOB
    db_events = []
    if session:
         try:
            from app.models.treatment import Treatment as DBTreatment
            from sqlalchemy import select
            
            # Fetch last ~30 treatments (usually enough for DIA 4-6 hours)
            # Actually DIA 8 hours max implies we need recent checks.
            stmt = (
                select(DBTreatment)
                .where(DBTreatment.user_id == user.username) 
                .order_by(DBTreatment.created_at.desc())
                .limit(50)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            for row in rows:
                if row.insulin and row.insulin > 0:
                    created_iso = row.created_at.isoformat()
                    # Ensure UTC signaling if naive
                    if not created_iso.endswith("Z") and "+" not in created_iso:
                        created_iso += "Z"
                    db_events.append({"ts": created_iso, "units": float(row.insulin)})
         except Exception as db_err:
             logger.error(f"Failed to fetch DB events for IOB: {db_err}")

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
        iob_u, breakdown, iob_info, iob_warning = await compute_iob_from_sources(
            now, user_settings, ns_client, store, extra_boluses=db_events
        )
        
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
        response.iob_u = round(iob_u, 2) # ensure correct assignment

        if iob_warning:
            response.warnings.append(iob_warning)
        
        if breakdown:
             response.explain.append(f"   (IOB basado en {len(breakdown)} tratamientos recientes)")
        
        return response

    finally:
        if ns_client:
            await ns_client.aclose()


class BolusAcceptRequest(BaseModel):
    insulin: float = Field(ge=0)
    duration: float = Field(default=0.0, description="Duration in minutes for extended bolus")
    carbs: float = Field(default=0, ge=0)
    created_at: str
    notes: Optional[str] = ""
    enteredBy: str = "BolusAI"
    nightscout: Optional[dict] = None  # {url, token}
    meal_meta: Optional[dict] = None # {items: [], fat: 0, protein: 0, strategy: {}}


@router.post("/treatments", summary="Save a treatment (bolus) to NS/Local/DB")
async def save_treatment(
    payload: BolusAcceptRequest,
    user: CurrentUser = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
    session: AsyncSession = Depends(get_db_session)
):
    import uuid
    from app.services.learning_service import LearningService
    
    # Optional: Save Meal Learning Data
    if payload.meal_meta and session:
        try:
            ls = LearningService(session)
            # Context (bg/trend) could be parsed from payload if we added it, 
            # or we rely on what we have. 
            # For now passing basic context from payload if available implicitly or none.
            # Assuming payload.notes might contain BG info or we add it to meal_meta later.
            
            await ls.save_meal_entry(
                user_id=user.username,
                items=payload.meal_meta.get("items", []),
                carbs=payload.carbs,
                fat=payload.meal_meta.get("fat", 0),
                protein=payload.meal_meta.get("protein", 0),
                bolus_data=payload.meal_meta.get("strategy", {}),
                context={} # Todo: Pass BG/Trend explicitly if needed
            )
        except Exception as e:
            logger.error(f"Failed to save meal learning entry: {e}")

    # 1. Save locally (Always, as backup)
    treatment_id = str(uuid.uuid4())
    treatment_data = {
        "_id": treatment_id,
        "id": treatment_id,
        "eventType": "Correction Bolus" if payload.carbs == 0 else "Meal Bolus",
        "created_at": payload.created_at,
        "insulin": payload.insulin,
        "duration": payload.duration,
        "carbs": payload.carbs,
        "notes": payload.notes,
        "enteredBy": payload.enteredBy,
        "type": "bolus",
        "ts": payload.created_at, 
        "units": payload.insulin   
    }
    
    events = store.load_events()
    events.append(treatment_data)
    if len(events) > 1000:
        events = events[-1000:]
    store.save_events(events)
    
    # 2. Save to Database (Robust Persistence)
    # We use the same session provided by dependency
    if session:
        from app.models.treatment import Treatment
        try:
            # Parse date
            # Parse date and ensure it is naive UTC (for timestamp without time zone)
            dt_aware = datetime.fromisoformat(payload.created_at.replace('Z', '+00:00'))
            dt = dt_aware.astimezone(timezone.utc).replace(tzinfo=None)
            
            db_treatment = Treatment(
                id=treatment_id,
                user_id=user.username,
                event_type=treatment_data["eventType"],
                created_at=dt,
                insulin=payload.insulin,
                duration=payload.duration,
                carbs=payload.carbs,
                notes=payload.notes,
                entered_by=payload.enteredBy,
                is_uploaded=False 
            )
            session.add(db_treatment)
            await session.commit()
            logger.info("Treatment saved to Database")
        except Exception as db_err:
            logger.error(f"Failed to save treatment to DB: {db_err}")
            # Don't crash, we have local backup
    
    # 3. Upload to Nightscout if configured
    ns_uploaded = False
    error = None
    
    ns_config = await get_ns_config(session, user.username)
    
    if ns_config and ns_config.enabled and ns_config.url:
        ns_url = ns_config.url
        ns_token = ns_config.api_secret
    else:
        ns_url = payload.nightscout.get("url") if payload.nightscout else None
        ns_token = payload.nightscout.get("token") if payload.nightscout else None
    
    if not ns_url:
        error = "Nightscout not configured (neither in DB nor payload)"

    if ns_url:
        try:
            client = NightscoutClient(ns_url, ns_token, timeout_seconds=5)
            ns_payload = {
                "eventType": treatment_data["eventType"],
                "created_at": payload.created_at,
                "insulin": payload.insulin,
                "duration": payload.duration,
                "carbs": payload.carbs,
                "notes": payload.notes,
                "enteredBy": payload.enteredBy,
            }
            await client.upload_treatments([ns_payload])
            await client.aclose()
            ns_uploaded = True
            # Mark DB record as uploaded if we have it
            try:
                db_treatment.is_uploaded = True
                await session.commit()
            except Exception as e2:
                logger.error(f"Failed to update upload flag in DB: {e2}")
            
        except Exception as e:
            logger.error(f"Failed to upload treatment to NS: {e}")
            error = str(e)
            
    return {
        "success": True,
        "ns_uploaded": ns_uploaded,
        "ns_error": error
    }


@router.get("/iob", summary="Get current IOB and decay curve")
async def get_current_iob(
    store: DataStore = Depends(_data_store),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    # Construct settings or load
    from app.services.settings_service import get_user_settings_service
    settings = None
    if session:
        try:
             data = await get_user_settings_service(user.username, session)
             if data and data.get("settings"):
                 settings = UserSettings.migrate(data["settings"])
        except:
             pass
    if not settings:
        settings = store.load_settings()
    
    # NS Client
    ns_client = None
    
    # Fetch user specific NS config
    ns_config = await get_ns_config(session, user.username)
    
    eff_url = ns_config.url if ns_config and ns_config.enabled else None
    eff_token = ns_config.api_secret if ns_config and ns_config.enabled else None
    
    if eff_url:
        ns_client = NightscoutClient(eff_url, eff_token, timeout_seconds=5)
        
        # Fetch DB treatments for IOB
    db_events = []
    if session:
         try:
            from app.models.treatment import Treatment as DBTreatment
            from sqlalchemy import select
            
            stmt = (
                select(DBTreatment)
                .where(DBTreatment.user_id == user.username) 
                .order_by(DBTreatment.created_at.desc())
                .limit(50)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            for row in rows:
                if row.insulin and row.insulin > 0:
                    created_iso = row.created_at.isoformat()
                    if not created_iso.endswith("Z") and "+" not in created_iso:
                        created_iso += "Z"
                    db_events.append({"ts": created_iso, "units": float(row.insulin)})
         except Exception as db_err:
             logger.error(f"Failed to fetch DB events for IOB: {db_err}")

    try:
        now = datetime.now(timezone.utc)
        total_iob, breakdown, iob_info, iob_warning = await compute_iob_from_sources(
            now, settings, ns_client, store, extra_boluses=db_events
        )
        
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
