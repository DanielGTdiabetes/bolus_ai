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
from app.services.autosens_service import AutosensService
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.services.nightscout_client import NightscoutClient, NightscoutError
from app.services.store import DataStore
from app.core.db import get_db_session
from app.services.nightscout_secrets_service import get_ns_config
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import CurrentUser
from app.services.treatment_logger import log_treatment

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
        from app.models.settings import MealFactors, CorrectionFactors, TargetRange, IOBConfig, NightscoutConfig, AutosensConfig
        
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
        
        # Map insulin_model to curve
        c_model = getattr(payload.settings, "insulin_model", "walsh")
        # Ensure it is a valid curve string
        if c_model not in ["walsh", "bilinear", "fiasp", "novorapid", "linear"]:
             c_model = "walsh"
             
        iob_settings = IOBConfig(
             dia_hours=payload.settings.dia_hours,
             curve=c_model, 
             peak_minutes=payload.settings.insulin_peak_minutes 
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
            autosens=AutosensConfig(enabled=payload.enable_autosens) if payload.enable_autosens is not None else AutosensConfig(), 
            max_bolus_u=payload.settings.max_bolus_u,
            max_correction_u=payload.settings.max_correction_u,
            round_step_u=payload.settings.round_step_u
        )
        
        if payload.target_mgdl is None:
             slot_profile = getattr(payload.settings, payload.meal_slot)
             payload.target_mgdl = slot_profile.target

    elif payload.cr_g_per_u:
        from app.models.settings import MealFactors, CorrectionFactors, TargetRange, IOBConfig, NightscoutConfig, WarsawConfig
        
        # Apply single CR/ISF to ALL slots for safety/simplicity in this stateless request
        cr_val = payload.cr_g_per_u
        isf_val = payload.isf_mgdl_per_u or 30.0
        
        cr_settings = MealFactors(breakfast=cr_val, lunch=cr_val, dinner=cr_val)
        isf_settings = CorrectionFactors(breakfast=isf_val, lunch=isf_val, dinner=isf_val)
        
        target_settings = TargetRange(low=70, mid=payload.target_mgdl or 100, high=180)
        
        iob_settings = IOBConfig(
             dia_hours=payload.dia_hours or 4.0,
             curve="walsh", # Default to Walsh for overrides if not specified
             peak_minutes=75
        )
        
        ns_settings = NightscoutConfig(
            enabled=bool(payload.nightscout and payload.nightscout.url),
            url=payload.nightscout.url if payload.nightscout else "",
            token=payload.nightscout.token if payload.nightscout else ""
        )
        
        warsaw_settings = WarsawConfig()
        if payload.warsaw_safety_factor is not None:
             warsaw_settings.safety_factor = payload.warsaw_safety_factor
        if payload.warsaw_safety_factor_dual is not None:
             warsaw_settings.safety_factor_dual = payload.warsaw_safety_factor_dual
        if payload.warsaw_trigger_threshold_kcal is not None:
             warsaw_settings.trigger_threshold_kcal = payload.warsaw_trigger_threshold_kcal
        
        user_settings = UserSettings(
            cr=cr_settings,
            cf=isf_settings,
            targets=target_settings,
            iob=iob_settings,
            nightscout=ns_settings,
            warsaw=warsaw_settings,
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

    # Inject Last Bolus Time (Safety for Micro-Boluses)
    if db_events:
        # db_events is sorted desc, so [0] is latest
        try:
            latest = db_events[0]
            lat_ts = datetime.fromisoformat(latest["ts"])
            if lat_ts.tzinfo is None: lat_ts = lat_ts.replace(tzinfo=timezone.utc)
            
            now_ts = datetime.now(timezone.utc)
            diff_min = int((now_ts - lat_ts).total_seconds() / 60)
            
            if diff_min >= 0:
                payload.last_bolus_minutes = diff_min
                logger.info(f"Safety: Detected last bolus {diff_min} min ago ({latest['units']} U)")
        except Exception as e:
            logger.warning(f"Failed to calc last bolus time: {e}")

    # 4. Calculate IOB
    # Ensure client exists if needed for IOB even if BG was manual
    if ns_client is None and ns_config.enabled and ns_config.url:
         ns_client = NightscoutClient(
            base_url=ns_config.url,
            token=ns_config.token,
            timeout_seconds=5
         )

    # 4. Autosens (if enabled)
    autosens_ratio = 1.0
    autosens_reason = None

    # Determine if we should run Autosens
    # Priority: Payload override > Settings > Default On
    # Wait, payload.enable_autosens is default True in model?
    # Let's check model default. If user explicitly sets it, we use it.
    # Actually, let's treat payload.enable_autosens as "Request to use it".
    # But we should respect global switch if payload didn't explicitly demand it?
    # Simple logic: If settings say OFF, we default to OFF unless payload forces ON.
    # Currently payload.enable_autosens defaults to True in Pydantic. 
    # Let's use: should_run = user_settings.autosens.enabled
    
    should_run_autosens = user_settings.autosens.enabled
    
    if should_run_autosens and session:
         try:
             # HYBRID AUTOSENS IMPLEMENTATION
             # 1. Macro Layer (Dynamic TDD) - Global State
             from app.services.dynamic_isf_service import DynamicISFService
             tdd_ratio = await DynamicISFService.calculate_dynamic_ratio(
                 username=user.username,
                 session=session,
                 settings=user_settings
             )

             # 2. Micro Layer (Local Deviations) - Local Correction
             # We use the existing AutosensService which now has clamped limits (0.9-1.1)
             local_ratio = 1.0
             local_reason = ""
             try:
                res = await AutosensService.calculate_autosens(
                    username=user.username,
                    session=session,
                    settings=user_settings
                )
                local_ratio = res.ratio
                if local_ratio != 1.0:
                    local_reason = f" + Local {res.reason}"
             except Exception:
                pass # Fail open to Macro only if Micro fails

             # 3. Combine
             autosens_ratio = tdd_ratio * local_ratio
             
             # Final Clamp for Safety (Global limits)
             autosens_ratio = max(0.6, min(1.4, autosens_ratio))
             
             autosens_reason = f"Híbrido: TDD {tdd_ratio:.2f}x * Local {local_ratio:.2f}x"
                 
             logger.info(f"Hybrid Autosens: {autosens_ratio} ({autosens_reason})")
         except Exception as e:
             logger.error(f"Hybrid Autosens failed: {e}")
             autosens_reason = "Error (usando 1.0)"

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
            glucose_info=glucose_info,
            autosens_ratio=autosens_ratio,
            autosens_reason=autosens_reason
        )

        # Inject IOB Info
        response.iob = iob_info
        response.iob_u = round(iob_u, 2) # ensure correct assignment

        if iob_warning:
            response.warnings.append(iob_warning)

        if resolved_bg is None:
            response.warnings.append("⚠️ NO SE DETECTÓ GLUCOSA. El cálculo NO incluye corrección.")
        
        if breakdown:
             response.explain.append(f"   (IOB basado en {len(breakdown)} tratamientos):")
             now_ts = datetime.now(timezone.utc)
             for b in breakdown:
                 # b['ts'] is iso string
                 try:
                     ts_dt = datetime.fromisoformat(b['ts'])
                     if ts_dt.tzinfo is None: ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                     diff_min = int((now_ts - ts_dt).total_seconds() / 60)
                     time_label = f"Hace {diff_min} min" if diff_min < 120 else f"Hace {diff_min // 60}h {diff_min % 60}m"
                 except:
                     time_label = b['ts'][11:16] # Fallback
                     
                 response.explain.append(f"    - {time_label}: {b['units']} U -> quedan {b['iob']:.2f} U")
        
        return response

    finally:
        if ns_client:
            await ns_client.aclose()


class BolusAcceptRequest(BaseModel):
    insulin: float = Field(ge=0)
    duration: float = Field(default=0.0, description="Duration in minutes for extended bolus")
    carbs: float = Field(default=0, ge=0)
    fat: float = Field(default=0, ge=0)
    protein: float = Field(default=0, ge=0)
    fiber: float = Field(default=0, ge=0)
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
                context={}, # Todo: Pass BG/Trend explicitly if needed
                fiber=payload.fiber
            )
        except Exception as e:
            logger.error(f"Failed to save meal learning entry: {e}")

    # Resolve Nightscout config preference (payload overrides DB only when present)
    ns_url = payload.nightscout.get("url") if payload.nightscout else None
    ns_token = payload.nightscout.get("token") if payload.nightscout else None

    if session and (not ns_url):
        try:
            ns_config = await get_ns_config(session, user.username)
            if ns_config and ns_config.enabled and ns_config.url:
                ns_url = ns_config.url
                ns_token = ns_config.api_secret
        except Exception as exc:
            logger.error(f"Failed to fetch NS config for treatment save: {exc}")

    created_dt = datetime.fromisoformat(payload.created_at.replace("Z", "+00:00"))
    result = await log_treatment(
        user_id=user.username,
        insulin=payload.insulin,
        carbs=payload.carbs,
        notes=payload.notes,
        entered_by=payload.enteredBy,
        event_type="Correction Bolus" if payload.carbs == 0 else "Meal Bolus",
        duration=payload.duration,
        fat=payload.fat,
        protein=payload.protein,
        fiber=payload.fiber,
        created_at=created_dt,
        store=store,
        session=session,
        ns_url=ns_url,
        ns_token=ns_token,
    )

    ns_error = result.ns_error
    
    # --- AUTOSENS ADVISOR TRIGGERS ---
    # We do this in background to avoid blocking the bolus response
    if session and user.username:
        # Define the async check job
        async def check_autosens_advisor(u_id: str):
             try:
                 # Re-acquire session/engine since passed session might be closed or local
                 from app.core.db import get_engine, AsyncSession
                 engine = get_engine()
                 if not engine: return
                 
                 async with AsyncSession(engine) as task_session:
                     from app.services.settings_service import get_user_settings_service
                     from app.services.autosens_service import AutosensService
                     from app.models.settings import UserSettings
                     from app.models.suggestion import ParameterSuggestion
                     from app.bot.service import send_autosens_alert, get_current_meal_slot
                     
                     # Load Config
                     s_data = await get_user_settings_service(u_id, task_session)
                     if not s_data: return
                     us = UserSettings.migrate(s_data["settings"])
                     
                     if not us.autosens.enabled: return # Respect Global Switch
                     
                     # Double check to prevent "risk" even if code was called
                     if not us.autosens.enabled: return
                     res = await AutosensService.calculate_autosens(u_id, task_session, us)
                     ratio = res.ratio
                     
                     # Threshold: Deviating at least 1% to avoid pure noise. 
                     # We rely mainly on the absolute unit difference below for significance.
                     if 0.99 <= ratio <= 1.01:
                         return # Pure noise
                         
                     # Determine Slot
                     slot = get_current_meal_slot(us)
                     current_isf = getattr(us.cf, slot, 30.0)
                     
                     # Calcs
                     # new_isf = current / ratio
                     new_isf = round(current_isf / ratio, 1)
                     
                     if abs(current_isf - new_isf) < 1.0:
                         logger.info(f"Autosens advisor skipped: {current_isf}->{new_isf} diff < 1.0")
                         return # Rounding makes it irrelevant
                     
                     # Create Suggestion Record (App Notification)
                     match_key = f"autosens_{slot}_{datetime.utcnow().date()}"
                     
                     # Check if we already spammed today
                     # (Optional: duplicate check)
                     
                     direction = "decrease" if new_isf < current_isf else "increase"
                     
                     sug = ParameterSuggestion(
                         user_id=u_id,
                         meal_slot=slot,
                         parameter="isf",
                         direction=direction,
                         reason=f"Autosens: {res.reason} (Ratio {ratio:.2f})",
                         evidence={
                             "ratio": ratio,
                             "source": "autosens_advisor",
                             "current_value": current_isf,
                             "suggested_value": new_isf,
                             "old_isf": current_isf, # redundant but keeping for back-compat if needed
                             "new_isf": new_isf
                         },
                         status="pending"
                     )
                     task_session.add(sug)
                     await task_session.commit()
                     await task_session.refresh(sug)
                     
                     # Notify via Bot (Telegram)
                     from app.core import config
                     chat_id = config.get_allowed_telegram_user_id()
                     if chat_id:
                         await send_autosens_alert(
                             chat_id=int(chat_id),
                             ratio=ratio,
                             slot=slot,
                             old_isf=current_isf,
                             new_isf=new_isf,
                             suggestion_id=str(sug.id)
                         )
                         
             except Exception as ex:
                 logger.error(f"Autosens advisor background task failed: {ex}")

        # Execute
        # Since we are in an async function, we can create a Task
        import asyncio
        asyncio.create_task(check_autosens_advisor(user.username))

    return {
        "success": result.ok,
        "treatment_id": result.treatment_id,
        "ns_uploaded": result.ns_uploaded,
        "ns_error": ns_error,
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
        # Fetch DB treatments for IOB
    db_events = []
    db_carbs = []
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
                created_iso = row.created_at.isoformat()
                if not created_iso.endswith("Z") and "+" not in created_iso:
                    created_iso += "Z"

                if row.insulin and row.insulin > 0:
                    db_events.append({"ts": created_iso, "units": float(row.insulin)})
                
                if row.carbs and row.carbs > 0:
                    db_carbs.append({"ts": created_iso, "carbs": float(row.carbs)}) # For COB

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
            active_boluses.append({
                "ts": b["ts"], 
                "units": b["units"],
                "duration": b.get("duration", 0)
            })
            
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
        total_cob = await compute_cob_from_sources(now, ns_client, store, extra_entries=db_carbs)

        return {
            "iob_total": round(total_iob, 2),
            "cob_total": round(total_cob, 0),
            "breakdown": breakdown, 
            "graph": curve_points, # Legacy name, actually IOB Curve
            "iob_info": iob_info.model_dump(),
            "warning": iob_warning
        }
        
    finally:
        if ns_client:
            await ns_client.aclose()
