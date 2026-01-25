from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal, Optional

import logging
from fastapi import APIRouter, Depends, HTTPException
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
from app.services.bolus_calc_service import calculate_bolus_stateless_service
from app.services.bolus_split import create_plan, recalc_second
from app.services.autosens_service import AutosensService
from app.services.smart_filter import CompressionDetector, FilterConfig
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.models.iob import SourceStatus
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

# --- ACTIVE PLANS MANAGEMENT ---

class ActivePlan(BaseModel):
    id: str
    created_at_ts: int
    upfront_u: float
    later_u_planned: float
    later_after_min: int
    extended_duration_min: Optional[int] = None
    status: Literal["pending", "completed", "cancelled"] = "pending"
    notes: Optional[str] = None

class ActivePlansList(BaseModel):
    plans: list[ActivePlan] = []

@router.post("/active-plans", summary="Save an active plan for bot tracking")
async def save_active_plan(
    plan: ActivePlan,
    store: DataStore = Depends(_data_store)
):
    # Load existing
    try:
        data = store.load_json("active_plans.json")
        current_list = ActivePlansList(**data)
    except:
        current_list = ActivePlansList()
    
    # Add new
    # Remove if exists (replace)
    current_list.plans = [p for p in current_list.plans if p.id != plan.id]
    current_list.plans.append(plan)
    
    store.save_json("active_plans.json", current_list.model_dump())
    logger.info(f"Saved active plan {plan.id} for bot tracking")
    return {"status": "ok"}

@router.get("/active-plans", response_model=ActivePlansList)
async def get_active_plans(store: DataStore = Depends(_data_store)):
    try:
        data = store.load_json("active_plans.json")
        return ActivePlansList(**data)
    except:
        return ActivePlansList()

@router.delete("/active-plans/{plan_id}")
async def delete_active_plan(plan_id: str, store: DataStore = Depends(_data_store)):
    try:
        data = store.load_json("active_plans.json")
        current_list = ActivePlansList(**data)
        current_list.plans = [p for p in current_list.plans if p.id != plan_id]
        store.save_json("active_plans.json", current_list.model_dump())
    except:
        pass
    return {"status": "ok"}

# -------------------------------

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
    return await calculate_bolus_stateless_service(
        payload,
        store=store,
        user=user,
        session=session,
    )


class BolusAcceptRequest(BaseModel):
    insulin: float = Field(ge=0)
    duration: float = Field(default=0.0, description="Duration in minutes for extended bolus")
    carbs: float = Field(default=0, ge=0)
    fat: float = Field(default=0, ge=0)
    protein: float = Field(default=0, ge=0)
    fiber: float = Field(default=0, ge=0)
    carb_profile: Optional[Literal["fast", "med", "slow"]] = None
    linked_ingestion: bool = False
    ingestion_id: Optional[str] = None
    created_at: str
    notes: Optional[str] = ""
    enteredBy: str = "BolusAI"
    nightscout: Optional[dict] = None  # {url, token}
    meal_meta: Optional[dict] = None # {items: [], fat: 0, protein: 0, strategy: {}}
    injection_site: Optional[str] = None # Explicit site ID for rotation sync


@router.post("/treatments", summary="Save a treatment (bolus) to NS/Local/DB")
async def save_treatment(
    payload: BolusAcceptRequest,
    user: CurrentUser = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
    session: AsyncSession = Depends(get_db_session)
):
    from app.services.learning_service import LearningService

    linked_ingestion = payload.linked_ingestion or bool(payload.ingestion_id)
    original_carbs = payload.carbs
    learning_carbs = payload.carbs
    learning_fat = payload.meal_meta.get("fat", payload.fat) if payload.meal_meta else payload.fat
    learning_protein = payload.meal_meta.get("protein", payload.protein) if payload.meal_meta else payload.protein
    learning_fiber = payload.meal_meta.get("fiber", payload.fiber) if payload.meal_meta else payload.fiber

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
                carbs=learning_carbs,
                fat=learning_fat,
                protein=learning_protein,
                bolus_data=payload.meal_meta.get("strategy", {}),
                context={}, # Todo: Pass BG/Trend explicitly if needed
                fiber=learning_fiber
            )
        except Exception as e:
            logger.error(f"Failed to save meal learning entry: {e}")

    # --- FIX: Ensure macros are populated from meal_meta if missing in top-level ---
    # Some frontend flows (e.g. Favorites) might populate meal_meta but leave top-level fat/protein as 0.
    if payload.meal_meta and not linked_ingestion:
        if payload.fat <= 0 and "fat" in payload.meal_meta:
            try:
                payload.fat = float(payload.meal_meta["fat"])
                logger.debug(f"Populated missing fat from meal_meta: {payload.fat}")
            except: pass
            
        if payload.protein <= 0 and "protein" in payload.meal_meta:
            try:
                payload.protein = float(payload.meal_meta["protein"])
                logger.debug(f"Populated missing protein from meal_meta: {payload.protein}")
            except: pass

        if payload.fiber <= 0 and "fiber" in payload.meal_meta:
            try:
                payload.fiber = float(payload.meal_meta["fiber"])
                logger.debug(f"Populated missing fiber from meal_meta: {payload.fiber}")
            except: pass
            
    if linked_ingestion:
        payload.carbs = 0.0
        payload.fat = 0.0
        payload.protein = 0.0
        payload.fiber = 0.0
        if payload.notes:
            payload.notes = f"{payload.notes} [linked_ingestion_id={payload.ingestion_id or 'unknown'}]"
        else:
            payload.notes = f"[linked_ingestion_id={payload.ingestion_id or 'unknown'}]"

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
        carb_profile=payload.carb_profile,
        notes=payload.notes,
        entered_by=payload.enteredBy,
        event_type="Correction Bolus" if original_carbs == 0 else "Meal Bolus",
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
                     res = await AutosensService.calculate_autosens(
                         u_id,
                         task_session,
                         us,
                         compression_config=compression_config,
                     )
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

    # --- ROTATION SYNC ---
    if payload.injection_site and payload.insulin > 0:
        try:
             # Update global rotation state (persist manual selection)
             from app.services.async_injection_manager import AsyncInjectionManager
             mgr = AsyncInjectionManager(user.username if user else "admin")
             kind = "basal" if "leg" in payload.injection_site or "glute" in payload.injection_site else "bolus"
             await mgr.set_current_site(kind, payload.injection_site, source="manual")
             logger.info(f"Updated rotation state to {payload.injection_site} (kind={kind}, source=manual)")
        except Exception as e:
            logger.error(f"Failed to sync rotation state: {e}")

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
            now, settings, ns_client, store, extra_boluses=db_events, user_id=user.username
        )
        total_cob, cob_info, cob_source_status = await compute_cob_from_sources(
            now,
            ns_client,
            store,
            extra_entries=db_carbs,
            user_id=user.username,
        )
        if not iob_info.glucose_source_status:
            iob_info.glucose_source_status = SourceStatus(source="unknown", status="unknown", fetched_at=now)
        
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
        iob_total_val = round(total_iob, 2) if total_iob is not None else None
        cob_total_val = round(total_cob, 0) if total_cob is not None else None

        return {
            "iob_total": iob_total_val,
            "cob_total": cob_total_val,
            "breakdown": breakdown, 
            "graph": curve_points, # Legacy name, actually IOB Curve
            "iob_info": iob_info.model_dump(),
            "cob_info": cob_info.model_dump(),
            "glucose_source_status": iob_info.glucose_source_status.model_dump() if iob_info.glucose_source_status else None,
            "treatments_source_status": (iob_info.treatments_source_status.model_dump() if iob_info.treatments_source_status else cob_source_status.model_dump()),
            "warning": iob_warning
        }
        
    finally:
        if ns_client:
            await ns_client.aclose()
