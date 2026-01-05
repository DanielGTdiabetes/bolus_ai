from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.bot.state import health
from app.core.settings import get_settings
from app.core.db import get_engine, AsyncSession
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient, NightscoutError
from app.services.dexcom_client import DexcomClient
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2, GlucoseUsed as GlucoseUsedV2
from app.services.forecast_engine import ForecastEngine
from app.models.forecast import (
    ForecastSimulateRequest,
    ForecastEvents,
    ForecastEventBolus,
    ForecastEventCarbs,
    SimulationParams,
    MomentumConfig,
)
from app.services.bolus_engine import calculate_bolus_v2
from app.models.settings import UserSettings
from app.services.treatment_logger import log_treatment
from app.services.suggestion_engine import generate_suggestions_service, get_suggestions_service, resolve_suggestion_service
from app.services.rotation_service import RotationService
from app.api.user_data import FavoriteCreate, FavoriteRead
from app.models.user_data import FavoriteFood
from app.services.autosens_service import AutosensService
from app.services.autosens_service import AutosensService
from app.bot.user_settings_resolver import resolve_bot_user_settings
from app.services.restaurant_db import RestaurantDBService
from app.models.user_data import FavoriteFood, SupplyItem
from app.api.user_data import SupplyRead, SupplyUpdate

logger = logging.getLogger(__name__)


class ToolError(BaseModel):
    type: str
    message: str


class BolusContext(BaseModel):
    bg_mgdl: Optional[float] = None
    direction: Optional[str] = None
    delta: Optional[float] = None
    iob_u: Optional[float] = None
    cob_g: Optional[float] = None
    timestamp: Optional[str] = None
    age_minutes: Optional[float] = None # Explicit age from source to avoid re-calc errors
    config_hash: Optional[str] = None # Security: Configuration Snapshot Hash
    quality: str = "unknown"
    source: str = "unknown"
    
    # Daily Totals (Awareness)
    daily_insulin_u: float = 0.0
    daily_carbs_g: float = 0.0
    daily_fat_g: float = 0.0
    daily_protein_g: float = 0.0
    daily_fiber_g: float = 0.0


# Alias for backward compatibility if needed, though we will update usages
StatusContext = BolusContext

class BolusResult(BaseModel):
    units: float
    explanation: List[str]
    confidence: str = "high"
    quality: str = "ok"
    recommended_site: Optional[Dict[str, Any]] = None


class CorrectionResult(BaseModel):
    units: float
    explanation: List[str]
    confidence: str = "high"
    quality: str = "ok"


class WhatIfResult(BaseModel):
    summary: str
    ending_bg: Optional[float] = None
    min_bg: Optional[float] = None
    max_bg: Optional[float] = None
    warnings: List[str] = []
    quality: str = "medium"


class NightscoutStats(BaseModel):
    range_hours: int
    avg_bg: Optional[float] = None
    tir_pct: Optional[float] = None
    lows: int = 0
    highs: int = 0
    min_bg_val: Optional[float] = None
    max_bg_val: Optional[float] = None
    sample_size: int = 0
    quality: str = "unknown"


class TempMode(BaseModel):
    mode: str = Field(..., pattern="^(sport|sick|normal|alcohol)$") # Alcohol mode supported
    expires_minutes: int = Field(default=180, ge=15, le=720)
    note: Optional[str] = None


class AddTreatmentRequest(BaseModel):
    carbs: Optional[float] = None
    insulin: Optional[float] = None
    fat: Optional[float] = None
    protein: Optional[float] = None
    fiber: Optional[float] = None
    notes: Optional[str] = None
    replace_id: Optional[str] = None
    event_type: Optional[str] = None


class AddTreatmentResult(BaseModel):
    ok: bool
    treatment_id: Optional[str] = None
    insulin: Optional[float] = None
    carbs: Optional[float] = None
    ns_uploaded: Optional[bool] = None
    ns_error: Optional[str] = None
    saved_db: Optional[bool] = None
    saved_local: Optional[bool] = None
    injection_site: Optional[Dict[str, Any]] = None
    replaced_id: Optional[str] = None

class SaveFavoriteResult(BaseModel):
    ok: bool
    favorite: Optional[FavoriteRead] = None
    error: Optional[str] = None

class SearchFoodResult(BaseModel):
    found: bool
    items: List[FavoriteRead] = []
    error: Optional[str] = None

class InjectionSiteResult(BaseModel):
    id: Optional[str] = None
    name: str
    emoji: str
    image: Optional[str] = None


    quality: str = "ok"


class RestaurantSessionResult(BaseModel):
    ok: bool
    session_id: Optional[str] = None
    status: str
    summary: Optional[str] = None
    error: Optional[str] = None



class OptimizationResult(BaseModel):
    suggestions: List[Dict[str, Any]]
    run_summary: Dict[str, Any]
    quality: str = "ok"


class ConfigureBasalReminderResult(BaseModel):
    ok: bool
    enabled: bool
    time_local: str
    expected_units: float
    error: Optional[str] = None


class SupplyCheckResult(BaseModel):
    items: List[Dict[str, Any]]
    low_stock_warnings: List[str] = []
    quality: str = "ok"



def _build_ns_client(settings: UserSettings | None) -> Optional[NightscoutClient]:
    if not settings or not settings.nightscout.url:
        return None
    base = settings.nightscout.url
    if not base.startswith("http"):
        base = "https://" + base
    return NightscoutClient(
        base_url=base,
        token=settings.nightscout.token,
        timeout_seconds=10,
    )



async def _resolve_user_id(session: Optional[AsyncSession] = None) -> str:
    """Helper to find the active username for tool operations."""
    try:
        from sqlalchemy import text
        # If we have a session, try to find the first user in settings
        if session:
            # 1. Try 'admin' explicitly first as it's the standard default
            from app.services.settings_service import get_user_settings_service
            res = await get_user_settings_service("admin", session)
            if res and res.get("settings"):
                return "admin"
                
                return "admin"
                
            # 2. Fallback: Use the resolver logic to find the freshest user
            from app.bot.user_settings_resolver import resolve_bot_user_settings
            try:
                # We want the user ID that the bot would naturally pick
                _, resolved_id = await resolve_bot_user_settings(None)
                return resolved_id
            except:
                pass
                
        # If no session or no users found, default to admin
        return "admin"
    except Exception:
        # Unexpected error (e.g. table not created yet), return admin
        return "admin"


async def _load_user_settings(username: Optional[str] = None) -> UserSettings:
    """Load user settings using the shared resolver to avoid default/admin drift."""
    resolved_settings, resolved_user = await resolve_bot_user_settings(username)
    logger.info("Tools module using settings for user_id='%s'", resolved_user)
    return resolved_settings


async def get_status_context(username: str = "admin", user_settings: Optional[UserSettings] = None) -> BolusContext | ToolError:
    try:
        user_settings = user_settings or await _load_user_settings(username)
    except Exception as exc:
        return ToolError(type="config_error", message=f"No se pudo leer configuración: {exc}")

    ns_client = _build_ns_client(user_settings)
    now = datetime.now(timezone.utc)
    timestamp_str = now.isoformat()
    quality = "degraded"
    bg_val = None
    direction = None
    delta = None

    ns_sgv = None
    ns_age_min = 9999
    
    # 1. Try Nightscout
    if ns_client:
        try:
            # Add timestamp to params to bust cache? NightscoutClient handles params.
            # We can't easily add params here without modifying Client.
            # But let's log extensively first.
            ns_sgv = await ns_client.get_latest_sgv()
            
            ts_epoch_ms = float(ns_sgv.date)
            # Ensure we are checking UTC
            naive_ts = datetime.fromtimestamp(ts_epoch_ms / 1000.0)
            ts = datetime.fromtimestamp(ts_epoch_ms / 1000.0, timezone.utc)
            
            # Recalculate NOW to be extremely precise
            now_utc = datetime.now(timezone.utc)
            # Use pre-calculated age or relative
            age_min = (now_utc - ts).total_seconds() / 60
            
            # Debug log removed as issue is resolved


            # Use it if reasonably fresh or if we have no other options yet
            bg_val = float(ns_sgv.sgv)
            direction = ns_sgv.direction or None
            delta = ns_sgv.delta
            timestamp_str = ts.isoformat()
            quality = "live"
            ns_age_min = age_min
            
        except Exception as exc:
            logger.warning("NS sgv fetch failed: %s", exc)

    # 2. Dexcom Fallback (If NS failed OR is stale > 10 min)
    # We prioritize Nightscout (as per config), but if it's old/broken, we try Dexcom
    use_dexcom = False
    if bg_val is None: # NS Failed
        use_dexcom = True
    elif ns_age_min > 10: # NS Stale
        use_dexcom = True
        
    if use_dexcom and user_settings.dexcom and user_settings.dexcom.enabled:
        if user_settings.dexcom.username and user_settings.dexcom.password:
            try:
                logger.info("Values missing or stale (age=%.1f), attempting Dexcom Share fallback...", ns_age_min)
                dex = DexcomClient(
                    username=user_settings.dexcom.username,
                    password=user_settings.dexcom.password,
                    region=user_settings.dexcom.region
                )
                dx_reading = await dex.get_latest_sgv()
                if dx_reading:
                    # check if dexcom is actually newer than NS (if NS existed)
                    dx_age = (now - dx_reading.date).total_seconds() / 60
                    
                    if dx_age < ns_age_min:
                         bg_val = float(dx_reading.sgv)
                         direction = dx_reading.trend
                         delta = None # Dexcom client might not give delta easily
                         timestamp_str = dx_reading.date.isoformat()
                         quality = "live"
                         # We abuse 'source' to indicate origin? BotContext source defaults to 'unknown'
                         # We can encode it in quality or just assume live.
                         logger.info("Using Dexcom Share data (age=%.1f)", dx_age)
                         # Set source explicit
                         # Note: BolusContext source field definition logic below relies on ns_client existence?
                         # We will fix source assignment.
            except Exception as e:
                logger.warning(f"Dexcom fallback failed: {e}")

    store = DataStore(Path(get_settings().data.data_dir))
    cob_g = None
    iob_u = None
    try:
        iob_u, _, _, _ = await compute_iob_from_sources(now, user_settings, ns_client, store)
        cob_g = await compute_cob_from_sources(now, ns_client, store)
    except Exception as exc:
        logger.warning("IOB/COB compute failed: %s", exc)
        quality = "degraded"
    finally:
        if ns_client:
            await ns_client.aclose()

    # Calculate Daily Totals (Since Midnight Local/User Time? Or UTC?)
    # User expects "Today's totals". Usually Midnight Local.
    # We infer local midnight from system time or settings TZ?
    # Let's stick to UTC midnight for consistency unless TZ provided.
    
    daily_stats = {
        "insulin": 0.0, "carbs": 0.0, "fat": 0.0, "protein": 0.0, "fiber": 0.0
    }
    
    # 1. DB Source (Primary)
    try:
        engine = get_engine()
        if engine:
             async with AsyncSession(engine) as session:
                  target_user = username
                  if username == "admin":
                       target_user = await _resolve_user_id(session)
                  
                  # Naive Midnight? Or Smart?
                  # We use UTC midnight for simple "last 24h" window alignment? 
                  # No, "Daily Totals" means "Since 00:00".
                  # Let's assume server local time is user time for now (MVP).
                  from datetime import time
                  now_n = datetime.now()
                  midnight = now_n.replace(hour=0, minute=0, second=0, microsecond=0)
                  # Convert to UTC if created_at is UTC
                  start_of_day = midnight.astimezone(timezone.utc).replace(tzinfo=None) # Cast to naive for asyncpg
                  
                  from sqlalchemy import select, func
                  from app.models.treatment import Treatment

                  stmt = (
                      select(
                          func.sum(Treatment.insulin),
                          func.sum(Treatment.carbs),
                          func.sum(Treatment.fat),
                          func.sum(Treatment.protein),
                          func.sum(Treatment.fiber)
                      )
                      .where(Treatment.user_id == target_user)
                      .where(Treatment.created_at >= start_of_day)
                  )
                  row = (await session.execute(stmt)).fetchone()
                  if row:
                      daily_stats["insulin"] = row[0] or 0.0
                      daily_stats["carbs"] = row[1] or 0.0
                      daily_stats["fat"] = row[2] or 0.0
                      daily_stats["protein"] = row[3] or 0.0
                      daily_stats["fiber"] = row[4] or 0.0
                      
    except Exception as e:
        logger.warning(f"Failed to fetch daily stats from DB: {e}")

    # Determine final source label
    # valid_source logic:
    # - If we got fresh Dexcom data -> 'dexcom'
    # - If we rely on Nightscout (even if stale) -> 'nightscout'
    # - Else -> 'db_fallback' or 'unknown'
    

    # Re-eval source based on what we have
    # If we have a value and ns_client is unset -> db_fallback isn't quite right if we just have nothing.
    
    src = "unknown"
    if ns_sgv and not (use_dexcom and float(ns_sgv.sgv) != bg_val):
         src = "nightscout"
    
    # If we used Dexcom, bg_val would match dexcom reading. 
    # But strictly, if we successfully fetched Dexcom, we should label it.
    # Let's assume if use_dexcom is True and we have data, we likely tried. 
    # But if fallback failed, we still have stale NS data.
    # We should label based on the active data.
    
    # Let's use a heuristic:
    if use_dexcom and bg_val:
         # Check if value matches NS?
         if ns_sgv and abs(float(ns_sgv.sgv) - bg_val) < 0.1:
              src = "nightscout" # fallback failed, invalid, or identical
         else:
              src = "dexcom"
    elif ns_sgv:
         src = "nightscout"
    else:
         src = "db_fallback"

    return BolusContext(
        bg_mgdl=bg_val,
        direction=direction,
        delta=delta,
        iob_u=iob_u,
        cob_g=cob_g,
        timestamp=timestamp_str,
        age_minutes=ns_age_min if (ns_sgv or use_dexcom) else None,
        quality=quality,
        source=src,
        config_hash=user_settings.config_hash, 
        daily_insulin_u=round(daily_stats["insulin"], 2),
        daily_carbs_g=round(daily_stats["carbs"], 1),
        daily_fat_g=round(daily_stats["fat"], 1),
        daily_protein_g=round(daily_stats["protein"], 1),
        daily_fiber_g=round(daily_stats["fiber"], 1)
    )


async def calculate_bolus(carbs: float, fat: float = 0.0, protein: float = 0.0, fiber: float = 0.0, meal_type: Optional[str] = None, split: Optional[float] = None, extend_minutes: Optional[int] = None, alcohol: bool = False, target: Optional[float] = None) -> BolusResult | ToolError:
    try:
        user_settings = await _load_user_settings()
    except Exception as exc:
        return ToolError(type="config_error", message=f"Config no disponible: {exc}")

    # PHASE 2: Snapshot Context
    # We fetch status using the *just loaded* settings.
    # The context will contain bg, iob, and the config_hash of these settings.
    status = await get_status_context(user_settings=user_settings)
    if isinstance(status, ToolError):
        return status

    if meal_type:
        meal_slot = meal_type
    else:
        # Infer from system local time using User Settings Schedule
        from app.utils.timezone import to_local
        now_local = to_local(datetime.now())
        h = now_local.hour
        sch = user_settings.schedule
        
        if sch.breakfast_start_hour <= h < sch.lunch_start_hour:
            meal_slot = "breakfast"
        elif sch.lunch_start_hour <= h < sch.dinner_start_hour:
             meal_slot = "lunch"
        elif h >= sch.dinner_start_hour or h < sch.breakfast_start_hour:
             meal_slot = "dinner"
        else:
             meal_slot = "snack"

    # Check for Active Temp Modes (Global Override)
    try:
        store = DataStore(Path(get_settings().data.data_dir))
        events = store.load_events()
        now_utc = datetime.now(timezone.utc)
        
        for e in events:
            if e.get("type") == "temp_mode" and e.get("mode") == "alcohol":
                expires = e.get("expires_at")
                if expires:
                    try:
                        exp_dt = datetime.fromisoformat(expires)
                        if exp_dt.tzinfo is None: exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        if exp_dt > now_utc:
                            alcohol = True # Global override
                            break
                    except Exception: pass
    except Exception as e:
        logger.warning(f"Failed to check temp modes: {e}")

    # STALE DATA SAFETY CHECK
    is_stale_data = False
    
    # Use explicit age if available (more reliable), otherwise fallback to recalc
    current_age = status.age_minutes
    if current_age is None and status.bg_mgdl:
         try:
            ts = datetime.fromisoformat(status.timestamp)
            if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
            current_age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
         except: pass

    if status.bg_mgdl:
        if current_age is not None and current_age > 20:
             # Don't fail, just mark stale (Parity with App)
             logger.warning(f"Using stale glucose data ({int(current_age)} min old)")
             is_stale_data = True
    else:
        return ToolError(type="missing_data", message="No hay datos de glucosa recientes.")

    # Calculate Hybrid Autosens
    autosens_ratio = 1.0
    autosens_reason = None
    try:
        engine = get_engine()
        if engine:
             async with AsyncSession(engine) as session:
                  from app.bot.service import _resolve_user_id
                  u_id = await _resolve_user_id(session)
                  
                  # 1. Macro (TDD)
                  from app.services.dynamic_isf_service import DynamicISFService
                  tdd_ratio = await DynamicISFService.calculate_dynamic_ratio(u_id, session, user_settings)
                  
                  # 2. Micro (Local)
                  local_ratio = 1.0
                  try:
                       res = await AutosensService.calculate_autosens(u_id, session, user_settings)
                       local_ratio = res.ratio
                  except: pass
                  
                  # 3. Combine
                  autosens_ratio = tdd_ratio * local_ratio
                  autosens_ratio = max(0.6, min(1.4, autosens_ratio))
                  
                  if autosens_ratio != 1.0:
                       autosens_reason = f"Híbrido (TDD {tdd_ratio:.2f}x · Local {local_ratio:.2f}x)"
                  else:
                       autosens_reason = "Estable"
    except Exception as e:
        logger.warning(f"Bot Hybrid Autosens failed: {e}")
    
    # Build V2 Request
    req = BolusRequestV2(
        carbs_g=carbs,
        fat_g=fat,
        protein_g=protein,
        fiber_g=fiber,
        bg_mgdl=status.bg_mgdl,
        meal_slot=meal_slot,
        target_mgdl=target or user_settings.targets.mid,
        alcohol=alcohol,
        autosens_ratio=autosens_ratio,
        autosens_reason=autosens_reason
    )

    # Handle Split/Extend using V2 machinery
    if split is not None or extend_minutes is not None:
         req.slow_meal.enabled = True
         req.slow_meal.mode = "dual"
         if split: req.slow_meal.upfront_pct = split
         if extend_minutes: req.slow_meal.duration_min = extend_minutes

    iob_u = status.iob_u or 0.0
    
    # Glucose Info Wrapper
    # Map 'local' -> 'none' (or 'manual') to satisfy GlucoseUsed Literal restriction
    # status.source can be "local" coming from get_status_context
    valid_source = status.source
    if valid_source == "local":
        valid_source = "none" # Default to none if relying on local calc without external data
    
    glucose_info = GlucoseUsed(
        mgdl=status.bg_mgdl,
        source=valid_source,
        trend=status.direction,
        is_stale=is_stale_data
    )

    # Security: Log Config Hash from Context
    # We double-check that the settings object matches the context source
    # (In this flow they are identical, but this reinforces observability)
    cfg_hash = status.config_hash or user_settings.config_hash
    logger.info(f"Calculating bolus using config hash: {cfg_hash[:8]}")
    
    # Snapshot Timestamp Logic
    snap_ts = "Now"
    if status.timestamp:
        try:
            # Format nicely: 14:05:01
            dt_ts = datetime.fromisoformat(status.timestamp)
            from app.utils.timezone import to_local
            snap_ts = to_local(dt_ts).strftime("%H:%M:%S")
        except: pass

    rec = calculate_bolus_v2(req, user_settings, iob_u, glucose_info)
    
    explain = rec.explain
    if rec.warnings:
        explain.extend([f"⚠️ {w}" for w in rec.warnings])

    # Append Security Footprint
    explain.append(f"🔒 Hash: {cfg_hash[:6]} | 🕒 Datos: {snap_ts}")
    
    # Calculate Rotation Preview
    preview_site = None
    try:
        store = DataStore(Path(get_settings().data.data_dir))
        rotator = RotationService(store)
        # Resolve user (simple, rely on what we have, or default admin)
        # Ideally pass username from router but for now defaulting is safe for single user
        # We can try to peek at user_settings owner if available? No easiest is admin/default.
        target_user = "admin"
        preview = rotator.get_next_site_preview(target_user, plan="rapid")
        preview_site = {
             "id": preview.id,
             "name": preview.name,
             "emoji": preview.emoji,
             "image": preview.image_ref
        }
        explain.append(f"📍 Sugerencia: {preview.name} {preview.emoji}")
    except Exception as e:
        logger.warning(f"Rotation preview failed: {e}")

    return BolusResult(units=rec.total_u, explanation=explain, confidence="high", quality="data-driven", recommended_site=preview_site)


async def calculate_correction(target_bg: Optional[float] = None) -> CorrectionResult | ToolError:
    try:
        user_settings = await _load_user_settings()
    except Exception as exc:
        return ToolError(type="config_error", message=f"Config no disponible: {exc}")

    status = await get_status_context(user_settings=user_settings)
    if isinstance(status, ToolError):
        return status
    if status.bg_mgdl is None:
        return ToolError(type="missing_bg", message="No hay glucosa reciente (Nightscout caído o sin datos).")
    
    # Check age
    try:
        ts = datetime.fromisoformat(status.timestamp)
        if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        if age > 20: 
             return ToolError(type="stale_data", message=f"Datos antiguos ({int(age)}m). Riesgo de sobredosis.")
    except: pass

    target = target_bg or user_settings.targets.mid
    bg = status.bg_mgdl
    iob = status.iob_u or 0.0
    
    # Infer slot for ISF
    from app.utils.timezone import to_local
    now_local = to_local(datetime.now())
    h = now_local.hour
    sch = user_settings.schedule
    if sch.breakfast_start_hour <= h < sch.lunch_start_hour:
        slot = "breakfast"
    elif sch.lunch_start_hour <= h < sch.dinner_start_hour:
        slot = "lunch"
    elif h >= sch.dinner_start_hour or h < sch.breakfast_start_hour:
        slot = "dinner"
    else:
        slot = "snack"
        
    cf = getattr(user_settings.cf, slot, 50.0)
    correction_units = max((bg - target) / cf - iob, 0.0)
    explanation = [
        f"BG {bg} vs objetivo {target} con CF {cf} ({slot})",
        f"IOB restado: {iob:.2f} U",
    ]
    return CorrectionResult(units=round(correction_units, 2), explanation=explanation, confidence="medium", quality="live" if status.quality == "live" else "degraded")


async def simulate_whatif(carbs: float, horizon_minutes: int = 180) -> WhatIfResult | ToolError:
    try:
        user_settings = await _load_user_settings()
    except Exception as exc:
        return ToolError(type="config_error", message=f"No se pudo cargar configuración: {exc}")

    status = await get_status_context(user_settings=user_settings)
    if isinstance(status, ToolError):
        return status
    if status.bg_mgdl is None:
        return ToolError(type="missing_bg", message="No hay BG para simular (modo degradado).")

    # Simple simulation: carbs now, no insulin yet
    
    # SIMULATION:
    # 1. New Carbs (Proposed) at t=0
    sim_carbs = [ForecastEventCarbs(time_offset_min=0, grams=carbs, absorption_minutes=180)]
    
    # 2. History Carbs (Prevent Ghost COB)
    # Instead of lumping COB, we fetch recent treatments to model actual absorption curves.
    history_events = []
    try:
        # Use NS Client to get reliable history
        client = _build_ns_client(user_settings)
        if client:
            # Fetch 6h history
            recents = await client.get_recent_treatments(hours=6)
            now_utc = datetime.now(timezone.utc)
            
            for t in recents:
                # 2.1 Carbs
                if t.carbs and t.carbs > 0:
                    age_min = (now_utc - t.created_at).total_seconds() / 60
                    # Event time relative to NOW (t=0) is negative
                    offset = -1 * age_min
                    history_events.append(ForecastEventCarbs(
                        time_offset_min=int(offset),
                        grams=t.carbs,
                        absorption_minutes=180 # Default, or complex logic
                    ))
                
                # 2.2 Bolus History (for IOB simulation if needed, but engine usually calculates IOB separately. 
                # However, ForecastEngine logic might want Bolus events to compute IOB curve if we don't pass 'initial_iob'?)
                # Current ForecastEngine usually takes 'initial_iob' OR 'events'. 
                # If we pass initial_iob (computed by simple_iob), we might duplicate if we also pass bolus events.
                # Safest: Pass carb events for COB info, but rely on status.iob_u for IOB starting point?
                # Actually, status.cob_g is total COB. If we pass Carb Events, the engine re-calculates COB.
                # So if we pass Carb Events, we should NOT rely on status.cob_g for "initial_cob", or strictly one.
                # The engine 'initial_cob' param is typically an override or starting state.
                # Let's pass history events and let engine handle it.
                pass
                
            await client.aclose()
    except Exception as e:
        logger.warning(f"Simulate history fetch failed: {e}")
        # Fallback: Ghost Meal if history fetch fails
        if status.cob_g and status.cob_g > 5:
             sim_carbs.insert(0, ForecastEventCarbs(time_offset_min=0, grams=status.cob_g, absorption_minutes=120))

    # Merge
    all_carbs = history_events + sim_carbs

    events = ForecastEvents(
        boluses=[], # We rely on IOB being handled via 'initial_iob' implicitly or engine state? 
                    # Actually valid IOB comes from status.iob_u. The engine uses it if we don't simulate past boluses?
                    # Let's look at params below.
        carbs=all_carbs,
        basal_injections=[],
    )
    params = SimulationParams(
        isf=user_settings.cf.lunch,
        icr=user_settings.cr.lunch,
        dia_minutes=int(user_settings.iob.dia_hours * 60),
        carb_absorption_minutes=180,
        insulin_peak_minutes=user_settings.iob.peak_minutes,
        insulin_model="linear",
    )
    req = ForecastSimulateRequest(
        start_bg=status.bg_mgdl,
        horizon_minutes=horizon_minutes,
        step_minutes=5,
        params=params,
        events=events,
        momentum=MomentumConfig(enabled=True, lookback_points=3),
        initial_cob=None, # We use events now!
        recent_bg_series=[{"minutes_ago": 0, "value": status.bg_mgdl}],
    )
    forecast = ForecastEngine.calculate_forecast(req)
    summary = forecast.summary
    text = f"BG ahora {summary.bg_now} → {summary.bg_2h or summary.bg_30m} en horizonte. Min {summary.min_bg} / Max {summary.max_bg}."
    return WhatIfResult(
        summary=text,
        ending_bg=summary.ending_bg,
        min_bg=summary.min_bg,
        max_bg=summary.max_bg,
        warnings=forecast.warnings,
        quality=forecast.quality,
    )


async def get_nightscout_stats(range_hours: int = 24) -> NightscoutStats | ToolError:
    try:
        user_settings = await _load_user_settings()
    except Exception as exc:
        return ToolError(type="config_error", message=f"Config no disponible: {exc}")

    client = _build_ns_client(user_settings)
    if not client:
        return ToolError(type="missing_ns", message="Nightscout no configurado.")

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=range_hours)
    try:
        entries = await client.get_sgv_range(start, now, count=range_hours * 12 + 60)
    except NightscoutError as exc:
        return ToolError(type="ns_error", message=str(exc))
    finally:
        await client.aclose()

    values = [e.sgv for e in entries if e.sgv is not None]
    if not values:
        return NightscoutStats(range_hours=range_hours, quality="empty")
    
    # Stats
    lows = sum(1 for v in values if v < 70)
    highs = sum(1 for v in values if v > 250)
    tir = sum(1 for v in values if 70 <= v <= 180) / len(values) * 100
    avg = sum(values) / len(values)
    min_bg = min(values)
    max_bg = max(values)
    
    return NightscoutStats(
        range_hours=range_hours, 
        avg_bg=round(avg, 0), 
        tir_pct=round(tir, 1), 
        lows=lows, 
        highs=highs, 
        min_bg_val=min_bg, 
        max_bg_val=max_bg,
        sample_size=len(values), 
        quality="live"
    )



async def save_favorite_food(tool_input: dict[str, Any]) -> SaveFavoriteResult | ToolError:
    try:
        # Validate input manually or via Pydantic if defined
        name = tool_input.get("name")
        if not name:
            return ToolError(type="validation_error", message="El nombre es obligatorio")
            
        fav_create = FavoriteCreate(
            name=name,
            carbs=float(tool_input.get("carbs", 0)),
            fat=float(tool_input.get("fat", 0)),
            protein=float(tool_input.get("protein", 0)),
            fiber=float(tool_input.get("fiber", 0)),
            notes=tool_input.get("notes")
        )
        
        engine = get_engine()
        if not engine:
             return ToolError(type="db_error", message="Base de datos no disponible")
             
        async with AsyncSession(engine) as session:
             user_id = await _resolve_user_id(session)
             
             # Check if exists (by name, simple unique constraint simulation)
             from sqlalchemy import select
             stmt = select(FavoriteFood).where(FavoriteFood.user_id == user_id, FavoriteFood.name == fav_create.name)
             existing = (await session.execute(stmt)).scalar_one_or_none()
             
             if existing:
                 # Update existing
                 existing.carbs = fav_create.carbs
                 existing.fat = fav_create.fat
                 existing.protein = fav_create.protein
                 existing.fiber = fav_create.fiber
                 existing.notes = fav_create.notes
                 await session.commit()
                 await session.refresh(existing)
                 return SaveFavoriteResult(ok=True, favorite=FavoriteRead.from_orm(existing))
             else:
                 # Create new
                 new_fav = FavoriteFood(
                     user_id=user_id,
                     name=fav_create.name,
                     carbs=fav_create.carbs,
                     fat=fav_create.fat,
                     protein=fav_create.protein,
                     fiber=fav_create.fiber,
                     notes=fav_create.notes
                 )
                 session.add(new_fav)
                 await session.commit()
                 await session.refresh(new_fav)
                 return SaveFavoriteResult(ok=True, favorite=FavoriteRead.from_orm(new_fav))
             
    except Exception as e:
        logger.exception("Error saving favorite")
        return ToolError(type="runtime_error", message=str(e))


        return ToolError(type="runtime_error", message=str(e))


async def get_injection_site(tool_input: dict[str, Any]) -> InjectionSiteResult | ToolError:
    try:
        # Load store
        settings = get_settings()
        store = DataStore(Path(settings.data.data_dir))
        rotator = RotationService(store)
        
        engine = get_engine()
        user_id = "admin"
        if engine:
             async with AsyncSession(engine) as session:
                  user_id = await _resolve_user_id(session)

        site = rotator.get_next_site_preview(user_id) # Uses resolved user
        
        return InjectionSiteResult(
            id=site.id,
            name=site.name,
            emoji=site.emoji,
            image=site.image_ref
        )
    except Exception as e:
        logger.error(f"Error getting injection site: {e}")
        return ToolError(type="runtime_error", message=str(e))


async def get_last_injection_site(tool_input: dict[str, Any]) -> InjectionSiteResult | ToolError:
    try:
        # Load store
        settings = get_settings()
        store = DataStore(Path(settings.data.data_dir))
        rotator = RotationService(store)
        
        engine = get_engine()
        user_id = "admin"
        if engine:
             async with AsyncSession(engine) as session:
                  user_id = await _resolve_user_id(session)

        # We can detect plan from input if needed, but default to rapid for now
        plan = tool_input.get("plan", "rapid")
        site = rotator.get_last_site_preview(user_id, plan=plan)
        
        if not site:
             return ToolError(type="not_found", message="No hay registros de inyecciones previas.")

        return InjectionSiteResult(
            id=site.id,
            name=site.name,
            emoji=site.emoji,
            image=site.image_ref
        )
    except Exception as e:
        logger.error(f"Error getting last injection site: {e}")
        return ToolError(type="runtime_error", message=str(e))


async def search_food(tool_input: dict[str, Any]) -> SearchFoodResult | ToolError:
    query = tool_input.get("query", "").lower()
    if not query:
        return SearchFoodResult(found=False, items=[])
        
    engine = get_engine()
    if not engine:
         return ToolError(type="db_error", message="Base de datos no disponible")
         
    try:
        from sqlalchemy import select
        async with AsyncSession(engine) as session:
             user_id = await _resolve_user_id(session)
             stmt = select(FavoriteFood).where(FavoriteFood.user_id == user_id)
             res = await session.execute(stmt)
             all_favs = res.scalars().all()
             
             # Filter in python for simple LIKE/Fuzzy
             matches = [f for f in all_favs if query in f.name.lower()]
             
             return SearchFoodResult(found=len(matches) > 0, items=[FavoriteRead.from_orm(m) for m in matches])
    except Exception as e:
        logger.exception("Error searching food")
        return ToolError(type="runtime_error", message=str(e))



async def set_temp_mode(temp: TempMode) -> dict[str, Any]:
    settings = get_settings()
    store = DataStore(Path(settings.data.data_dir))
    events = store.load_events()
    expires_at = datetime.utcnow() + timedelta(minutes=temp.expires_minutes)
    events.append(
        {
            "type": "temp_mode",
            "mode": temp.mode,
            "note": temp.note,
            "expires_at": expires_at.isoformat(),
        }
    )
    store.save_events(events)
    return {"mode": temp.mode, "expires_at": expires_at.isoformat()}


async def add_treatment(tool_input: dict[str, Any]) -> AddTreatmentResult | ToolError:
    try:
        payload = AddTreatmentRequest.model_validate(tool_input)
    except ValidationError as exc:
        health.record_action("add_treatment", ok=False, error=str(exc))
        return ToolError(type="validation_error", message=str(exc))

    insulin = float(payload.insulin or 0)
    carbs = float(payload.carbs or 0)
    notes = payload.notes or "Chat Bot"
    store = DataStore(Path(get_settings().data.data_dir))
    engine = get_engine()
    result = None

    try:
        if engine:
            async with AsyncSession(engine) as session:
                user_id = await _resolve_user_id(session=session)
                result = await log_treatment(
                    user_id=user_id,
                    insulin=insulin,
                    carbs=carbs,
                    fat=float(payload.fat or 0),
                    protein=float(payload.protein or 0),
                    fiber=float(payload.fiber or 0),
                    notes=notes,
                    entered_by="TelegramBot",
                    event_type=payload.event_type or ("Correction Bolus" if carbs == 0 else "Meal Bolus"),
                    created_at=datetime.now(timezone.utc),
                    store=store,
                    session=session,
                )
        else:
            user_id = await _resolve_user_id()
            result = await log_treatment(
                user_id=user_id,
                insulin=insulin,
                carbs=carbs,
                fat=float(payload.fat or 0),
                protein=float(payload.protein or 0),
                fiber=float(payload.fiber or 0),
                notes=notes,
                entered_by="TelegramBot",
                event_type=payload.event_type or ("Correction Bolus" if carbs == 0 else "Meal Bolus"),
                created_at=datetime.now(timezone.utc),
                store=store,
                session=None,
            )
    except Exception as exc:  # pragma: no cover - unexpected runtime errors
        logger.exception("add_treatment execution failed")
        health.record_action("add_treatment", ok=False, error=str(exc))
        return ToolError(type="runtime_error", message=str(exc))

    if not result:
        err_msg = "No result from treatment logger"
        health.record_action("add_treatment", ok=False, error=err_msg)
        return ToolError(type="runtime_error", message=err_msg)

    error_text = result.ns_error if not result.ok else None
    if not result.ok and not error_text:
        error_text = "Persistencia fallida"

    # Handle replacement (Deleting the original draft if it exists)
    replaced_id = None
    if payload.replace_id and result.ok:
        try:
             # Delete from DB
             if engine:
                 async with AsyncSession(engine) as session:
                      from app.models.treatment import Treatment
                      from sqlalchemy import delete
                      stmt = delete(Treatment).where(Treatment.id == payload.replace_id)
                      await session.execute(stmt)
                      await session.commit()
                      replaced_id = payload.replace_id
             
             # Delete from Local Store
             # Store uses '_id' or 'id'
             try:
                 events = store.load_events()
                 original_len = len(events)
                 events = [e for e in events if e.get("id") != payload.replace_id and e.get("_id") != payload.replace_id]
                 if len(events) < original_len:
                      store.save_events(events)
                      replaced_id = payload.replace_id
             except Exception: pass
             
        except Exception as e:
            logger.error(f"Failed to delete replaced treatment {payload.replace_id}: {e}")

    # Rotation Logic
    site_info = None
    rotation_site = None
    if result.ok:
        # Learning Hook (Memory)
        if engine:
             try:
                from app.services.learning_service import LearningService
                async with AsyncSession(engine) as session:
                     ls = LearningService(session)
                     
                     strategy = {
                         "kind": "normal",
                         "total": insulin,
                         "upfront": insulin,
                         "later": 0,
                         "delay": 0
                     }
                     # Basic user resolution
                     l_user = "admin"
                     try:
                        l_user = await _resolve_user_id(session)
                     except: pass

                     # Empty context for now
                     await ls.save_meal_entry(
                         user_id=l_user,
                         items=[], # Auto-generate
                         carbs=carbs,
                         fat=float(payload.fat or 0),
                         protein=float(payload.protein or 0),
                         bolus_data=strategy,
                         context={},
                         notes=notes,
                         fiber=float(payload.fiber or 0)
                     )
             except Exception as mem_e:
                 logger.warning(f"Memory save failed: {mem_e}")

        try:
             # Need user_id used in logging. 
             # We resolve it inside the logic above but don't strictly have it here unless we kept it?
             # 'result' from log_treatment doesn't have user_id, but we did await _resolve_user_id()
             # Wait, in the code above user_id is in local scope of `if engine:`.
             # We need to resolve it reliably here.
             u_id = "admin" # Default
             if engine:
                  # We can't reuse the closed session. 
                  # But we can try to resolve again or assume admin if no session.
                  # Ideally log_treatment should return user_id used? No.
                  # Let's re-resolve quickly 
                  # Or better, just refactor `add_treatment` to resolve user_id earlier.
                  pass
             
             # Re-resolve (cheap local lookup usually)
             # Actually, let's just use the `store` we have.
             # Rotation service needs store.
             rotator = RotationService(store)
             
             # We need the username. logic:
             # If we are in `add_treatment`, we are likely 'admin' if single user. 
             # Let's peek at how we resolved it: `user_id = await _resolve_user_id(session=session)`
             # If we don't have the session anymore...
             # Let's assume 'admin' for MVP or try to resolve.
             # The correct way is to fetch user_id before logging and reuse it.
             
             # FIX: I will modify add_treatment logic slightly above to capture user_id
             # But i can't see the lines above easily in this 'Replace' block.
             # I will just use 'admin' as fallback, or re-run _resolve_user_id logic.
             
             target_user = "admin"
             try:
                 if engine:
                     async with AsyncSession(engine) as s:
                         target_user = await _resolve_user_id(s)
                 else:
                     target_user = await _resolve_user_id()
             except: pass
             
             # Rotate Injection Site (if confirmed via Telegram and not just "logged")
             # Usually adding treatment via bot means "I just did it" -> rotate
             rotation_site = None
             try:
                 if store:
                     rotator = RotationService(store)
                     check_str = (notes or "") + (payload.event_type or "")
                     plan = "basal" if "basal" in check_str.lower() else "rapid"
                     rotation_site = rotator.rotate_site(target_user, plan=plan)
             except Exception as e:
                 logger.warning(f"Rotation failed: {e}")
        except Exception as e: 
             logger.warning(f"Post-treatment logic failed: {e}")

        injection_site_dict = None
        if rotation_site:
            injection_site_dict = {
                "id": rotation_site.id,
                "name": rotation_site.name,
                "emoji": rotation_site.emoji,
                "image": rotation_site.image_ref
            }

    health.record_action("add_treatment", ok=result.ok, error=error_text)
    return AddTreatmentResult(
        ok=result.ok,
        treatment_id=result.treatment_id,
        insulin=result.insulin,
        carbs=result.carbs,
        ns_uploaded=result.ns_uploaded,
        ns_error=error_text,
        saved_db=result.saved_db,
        saved_local=result.saved_local,
        injection_site=injection_site_dict
    )


async def configure_basal_reminder(tool_input: dict[str, Any]) -> ConfigureBasalReminderResult | ToolError:
    try:
        enabled_val = tool_input.get("enabled")
        time_val = tool_input.get("time") # "HH:MM"
        units_val = tool_input.get("units")

        engine = get_engine()
        if not engine:
             return ToolError(type="db_error", message="Base de datos no disponible")

        async with AsyncSession(engine) as session:
             # 1. Resolve User
             user_id = await _resolve_user_id(session)
             
             # 2. Fetch Settings
             from app.services.settings_service import get_user_settings_service, update_user_settings_service, VersionConflictError
             
             current = await get_user_settings_service(user_id, session)
             settings_dict = current.get("settings")
             version = current.get("version", 0)
             
             if not settings_dict:
                 # Should not happen for active user, but handle gracefully
                 return ToolError(type="config_error", message="Usuario sin configuración base.")

             # 3. Modify
             # Navigate to bot.proactive.basal
             # Ensure structure exists
             if "bot" not in settings_dict: settings_dict["bot"] = {}
             if "proactive" not in settings_dict["bot"]: settings_dict["bot"]["proactive"] = {}
             if "basal" not in settings_dict["bot"]["proactive"]: settings_dict["bot"]["proactive"]["basal"] = {}
             
             basal_conf = settings_dict["bot"]["proactive"]["basal"]
             
             if enabled_val is not None:
                 # Accept various truths
                 if isinstance(enabled_val, str):
                     basal_conf["enabled"] = enabled_val.lower() in ("true", "1", "yes", "on")
                 else:
                     basal_conf["enabled"] = bool(enabled_val)
                     
             if time_val:
                 # Validate format HH:MM
                 try:
                     datetime.strptime(time_val, "%H:%M")
                     basal_conf["time_local"] = time_val
                 except ValueError:
                     return ToolError(type="validation_error", message="Formato de hora inválido. Usa HH:MM (ej. 22:00)")
             
             if units_val is not None:
                 try:
                     basal_conf["expected_units"] = float(units_val)
                 except ValueError:
                     return ToolError(type="validation_error", message="Unidades deben ser número.")

             # 4. Save
             try:
                 await update_user_settings_service(user_id, settings_dict, version, session)
             except VersionConflictError:
                 # Retry once? Or fail.
                 # Let's fail for now, bot can retry if needed, but in tool flow simple is better.
                 return ToolError(type="conflict_error", message="Conflicto de versión al guardar. Intenta de nuevo.")
             
             return ConfigureBasalReminderResult(
                 ok=True,
                 enabled=basal_conf.get("enabled", False),
                 time_local=basal_conf.get("time_local", "?"),
                 expected_units=basal_conf.get("expected_units", 0.0)
             )

    except Exception as e:
        logger.exception("Error configuring basal reminder")
        return ToolError(type="runtime_error", message=str(e))



async def get_optimization_suggestions(days: int = 7) -> OptimizationResult | ToolError:
    try:
        user_settings = await _load_user_settings()
        # Resolve User ID properly (from settings or default)
        # Usually settings don't have user_id field explicitly if loaded from file?
        # But we need user_id for DB queries.
        engine = get_engine()
        if not engine:
             return ToolError(type="db_error", message="No hay base de datos disponible para análisis.")
             
        async with AsyncSession(engine) as session:
            # We need a user_id. If "admin" is default...
            # The service expects user_id column matches.
            # Usually we use "admin" or get it from auth.
            # Let's assume 'admin' if likely single user mode, or check settings.
            user_id = "admin" # Default
            
            # 1. Run Analysis (Generate new)
            run_stats = await generate_suggestions_service(user_id, days, session, settings=user_settings)
            
            # 2. Fetch Pending
            suggestions_db = await get_suggestions_service(user_id, "pending", session)
            
            # Format
            sugs_list = []
            for s in suggestions_db:
                sugs_list.append({
                    "id": s.id,
                    "slot": s.meal_slot,
                    "param": s.parameter,
                    "reason": s.reason,
                    "evidence": s.evidence,
                    "created_at": s.created_at.isoformat()
                })
                
            return OptimizationResult(
                suggestions=sugs_list,
                run_summary=run_stats,
                quality="high"
            )

    except Exception as exc:
        logger.exception("Optimization suggestion failed")
        return ToolError(type="runtime_error", message=str(exc))


AI_TOOL_DECLARATIONS = [
    {
        "name": "get_status_context",
        "description": "Devuelve contexto de glucosa actual, tendencia, IOB, COB y calidad.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "calculate_bolus",
        "description": "Calcula recomendación de bolo para una comida. No aplica automáticamente.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "carbs": {"type": "NUMBER", "description": "Carbohidratos en gramos"},
                "meal_type": {"type": "STRING", "description": "breakfast/lunch/dinner/snack"},
                "split": {"type": "NUMBER", "description": "Porcentaje inicial si dual"},
                "extend_minutes": {"type": "INTEGER", "description": "Minutos de extensión si aplica"},
                "alcohol": {"type": "BOOLEAN", "description": "Activar modo alcohol (reduce correcciones)"}
            },
            "required": ["carbs"],
        },
    },
    {
        "name": "calculate_correction",
        "description": "Calcula corrección basada en BG actual y objetivo.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "target_bg": {"type": "NUMBER", "description": "Objetivo alternativo mg/dL"},
            },
        },
    },
    {
        "name": "simulate_whatif",
        "description": "Simula qué pasa si se ingieren carbohidratos ahora sin bolo.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "carbs": {"type": "NUMBER"},
                "horizon_minutes": {"type": "INTEGER", "description": "Horizonte en minutos", "default": 180},
            },
            "required": ["carbs"],
        },
    },
    {
        "name": "get_nightscout_stats",
        "description": "Devuelve stats simples de Nightscout en ventana seleccionada.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "range_hours": {"type": "INTEGER", "description": "Ventana en horas (24/168)", "default": 24},
            },
        },
    },
    {
        "name": "set_temp_mode",
        "description": "Activa modo temporal sport/sick/normal solo en contexto del bot.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {"type": "STRING", "enum": ["sport", "sick", "normal", "alcohol"]},
                "expires_minutes": {"type": "INTEGER", "description": "Duración en minutos", "default": 180},
                "note": {"type": "STRING"},
            },
            "required": ["mode"],
        },
    },
    {
        "name": "add_treatment",
        "description": "Registrar tratamiento manual (carbos/insulina) siempre con confirmación.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "carbs": {"type": "NUMBER"},
                "insulin": {"type": "NUMBER"},
                "notes": {"type": "STRING"},
                "fat": {"type": "NUMBER", "description": "Grasas (g)"},
                "protein": {"type": "NUMBER", "description": "Proteínas (g)"},
                "fiber": {"type": "NUMBER", "description": "Fibra (g)"},
            },
        },
    },
    {
        "name": "get_optimization_suggestions",
        "description": "Analiza patrones recientes (7 días) y sugiere cambios en ratios (ICR/ISF).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "days": {"type": "INTEGER", "description": "Días a analizar", "default": 7},
            },
        },
    },
    {
        "name": "save_favorite_food",
        "description": "Guardar comida en favoritos. Incluye carbos, grasas y proteínas.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "description": "Nombre único del plato"},
                "carbs": {"type": "NUMBER", "description": "Carbohidratos (g)"},
                "fat": {"type": "NUMBER", "description": "Grasas (g)"},
                "protein": {"type": "NUMBER", "description": "Proteínas (g)"},
                "fiber": {"type": "NUMBER", "description": "Fibra (g)"},
                "notes": {"type": "STRING"},
            },
            "required": ["name", "carbs"],
        },
    },
    {
        "name": "search_food",
        "description": "Buscar comidas en favoritos por nombre.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Texto a buscar"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_injection_site",
        "description": "Consultar siguiente punto de inyección recomendado (rotación). Devuelve imagen si es posible.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
    {
        "name": "get_last_injection_site",
        "description": "Consultar dónde se realizó la última inyección. Útil para recordar el sitio previo.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "plan": {"type": "STRING", "enum": ["rapid", "basal"], "description": "Tipo de insulina"}
            },
        },
    },

    {
        "name": "start_restaurant_session",
        "description": "Inicia sesión modo restaurante. Define carbohidratos esperados totales.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "expected_carbs": {"type": "NUMBER"},
                "expected_fat": {"type": "NUMBER"},
                "expected_protein": {"type": "NUMBER"},
                "notes": {"type": "STRING"}
            },
            "required": ["expected_carbs"]
        }
    },
    {
        "name": "add_plate_to_session",
        "description": "Añade un plato real a la sesión de restaurante activa.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "session_id": {"type": "STRING"},
                "carbs": {"type": "NUMBER"},
                "fat": {"type": "NUMBER"},
                "protein": {"type": "NUMBER"},
                "name": {"type": "STRING"}
            },
            "required": ["session_id", "carbs"]
        }
    },
    {
        "name": "end_restaurant_session",
        "description": "Finaliza sesión restaurante y calcula desviación.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "session_id": {"type": "STRING"},
                "outcome_score": {"type": "INTEGER", "description": "1-5"}
            },
            "required": ["session_id"]
        }
    },
    {
        "name": "check_supplies_stock",
        "description": "Consultar inventario de suministros (agujas, sensores, reservorios).",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        },
    },
    {
        "name": "update_supply_quantity",
        "description": "Actualizar cantidad de un suministro específico.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "item_key": {"type": "STRING", "description": "Clave del item (ej. supplies_needles, supplies_sensors). Si no sabe la clave, puede intentar 'agujas' o 'sensores' y el sistema intentará mapear."},
                "quantity": {"type": "INTEGER", "description": "Nueva cantidad total real."}
            },
            "required": ["item_key", "quantity"]
        },
    }
]


async def check_supplies_stock(tool_input: dict[str, Any]) -> SupplyCheckResult | ToolError:
    try:
        engine = get_engine()
        if not engine:
             return ToolError(type="db_error", message="Base de datos no disponible")
             
        items = []
        warnings = []
        
        async with AsyncSession(engine) as session:
             user_id = await _resolve_user_id(session)
             from sqlalchemy import select
             stmt = select(SupplyItem).where(SupplyItem.user_id == user_id)
             result = await session.execute(stmt)
             db_items = result.scalars().all()
             
             for item in db_items:
                 items.append({"name": item.item_key, "quantity": item.quantity})
                 # Check thresholds
                 # Default logic: if needles < 10, warn. if sensors < 2, warn.
                 if "aguja" in item.item_key.lower() or "needle" in item.item_key.lower():
                     if item.quantity < 10:
                         warnings.append(f"Quedan pocas agujas ({item.quantity})")
                 if "sensor" in item.item_key.lower():
                     if item.quantity < 3:
                         warnings.append(f"Quedan pocos sensores ({item.quantity})")
                 if "reservori" in item.item_key.lower() or "reservoir" in item.item_key.lower():
                     if item.quantity < 3:
                         warnings.append(f"Quedan pocos reservorios ({item.quantity})")
                         
        return SupplyCheckResult(items=items, low_stock_warnings=warnings)

    except Exception as e:
        logger.exception("Error checking supplies")
        # Debug to file
        try:
            with open("debug_supplies_error.txt", "w") as f:
                f.write(str(e))
                import traceback
                f.write(traceback.format_exc())
        except: pass
        return ToolError(type="runtime_error", message=f"Error consultando stock: {str(e)}")


async def update_supply_quantity(tool_input: dict[str, Any]) -> SupplyCheckResult | ToolError:
    try:
        key = tool_input.get("item_key") or tool_input.get("name")
        qty = tool_input.get("quantity")
        if not key or qty is None:
            return ToolError(type="validation_error", message="Falta nombre o cantidad")
            
        engine = get_engine()
        if not engine:
             return ToolError(type="db_error", message="DB no accesible")
             
        async with AsyncSession(engine) as session:
             user_id = await _resolve_user_id(session)
             from sqlalchemy import select
             stmt = select(SupplyItem).where(SupplyItem.user_id == user_id, SupplyItem.item_key == key)
             existing_item = (await session.execute(stmt)).scalar_one_or_none()
             
             if existing_item:
                 existing_item.quantity = int(qty)
             else:
                 new_item = SupplyItem(user_id=user_id, item_key=key, quantity=int(qty))
                 session.add(new_item)
             
             await session.commit()
             
        # Re-check to return status
        return await check_supplies_stock({}) 
        
    except Exception as e:
        logger.exception("Error updating supply")
        return ToolError(type="runtime_error", message=str(e))


async def start_restaurant_session(expected_carbs: float, expected_fat: float = 0.0, expected_protein: float = 0.0, notes: str = "") -> RestaurantSessionResult:
    try:
        user_settings = await _load_user_settings() # Gets admin/bot user
        engine = get_engine()
        user_id = "admin"
        if engine:
             async with AsyncSession(engine) as session:
                  user_id = await _resolve_user_id(session)

        sess = await RestaurantDBService.create_session(
            user_id=user_id,
            expected_carbs=expected_carbs,
            expected_fat=expected_fat,
            expected_protein=expected_protein,
            items=[],
            notes=notes
        )
        if sess:
            return RestaurantSessionResult(ok=True, session_id=str(sess.id), status="started", summary=f"Sesión iniciada. Esperado: {expected_carbs}g HC.")
        else:
             return RestaurantSessionResult(ok=False, status="error", error="DB no disponible")
    except Exception as e:
        logger.error(f"Error starting restaurant session: {e}")
        return RestaurantSessionResult(ok=False, status="error", error=str(e))


async def add_plate_to_session(session_id: str, carbs: float, fat: float = 0.0, protein: float = 0.0, name: str = "Plato") -> RestaurantSessionResult:
    try:
        plate = {
            "carbs": carbs,
            "fat": fat,
            "protein": protein,
            "name": name,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        res = await RestaurantDBService.add_plate(session_id, plate)
        if res:
            return RestaurantSessionResult(ok=True, session_id=str(res.id), status="updated", summary=f"Plato añadido. Total actual: {res.actual_carbs}g HC.")
        else:
            return RestaurantSessionResult(ok=False, status="error", error="Sesión no encontrada")
    except Exception as e:
        logger.error(f"Error adding plate: {e}")
        return RestaurantSessionResult(ok=False, status="error", error=str(e))


async def end_restaurant_session(session_id: str, outcome_score: int = None) -> RestaurantSessionResult:
    try:
        res = await RestaurantDBService.finalize_session(session_id, outcome_score)
        if res:
            diff = res.delta_carbs
            msg = f"Sesión finalizada. Desviación: {diff:+.1f}g HC."
            return RestaurantSessionResult(ok=True, session_id=str(res.id), status="closed", summary=msg)
        else:
            return RestaurantSessionResult(ok=False, status="error", error="Sesión no encontrada")
    except Exception as e:
        logger.error(f"Error closing session: {e}")
        return RestaurantSessionResult(ok=False, status="error", error=str(e))


# Map tool names to callables
async def execute_tool(name: str, args: Dict[str, Any]) -> Any:
    try:
        if name == "get_status_context":
            return await get_status_context(username=args.get("username", "admin"))
        if name == "calculate_bolus":
            return await calculate_bolus(
                carbs=float(args.get("carbs")),
                fiber=float(args.get("fiber", 0)),
                meal_type=args.get("meal_type"),
                split=args.get("split"),
                extend_minutes=args.get("extend_minutes"),
                alcohol=bool(args.get("alcohol", False)),
            )
        if name == "calculate_correction":
            return await calculate_correction(target_bg=args.get("target_bg"))
        if name == "simulate_whatif":
            horizon = int(args.get("horizon_minutes") or 180)
            return await simulate_whatif(carbs=float(args.get("carbs")), horizon_minutes=horizon)
        if name == "get_nightscout_stats":
            hours = int(args.get("range_hours") or 24)
            return await get_nightscout_stats(range_hours=hours)
        if name == "set_temp_mode":
            temp = TempMode.model_validate(args)
            return await set_temp_mode(temp)
        if name == "add_treatment":
            return await add_treatment(args)
        if name == "get_optimization_suggestions":
            return await get_optimization_suggestions(days=int(args.get("days") or 7))
        if name == "save_favorite_food":
            return await save_favorite_food(args)
        if name == "search_food":
            return await search_food(args)
        if name == "get_injection_site":
            return await get_injection_site(args)
        if name == "get_last_injection_site":
            return await get_last_injection_site(args)

        if name == "start_restaurant_session":
            return await start_restaurant_session(
                expected_carbs=float(args.get("expected_carbs")),
                expected_fat=float(args.get("expected_fat", 0)),
                expected_protein=float(args.get("expected_protein", 0)),
                notes=args.get("notes", "")
            )
        if name == "add_plate_to_session":
            return await add_plate_to_session(
                session_id=args.get("session_id"),
                carbs=float(args.get("carbs")),
                fat=float(args.get("fat", 0)),
                protein=float(args.get("protein", 0)),
                name=args.get("name", "Plato")
            )
        if name == "end_restaurant_session":
            return await end_restaurant_session(
                session_id=args.get("session_id"),
                outcome_score=int(args.get("outcome_score")) if args.get("outcome_score") else None
            )
        if name == "check_supplies_stock":
             return await check_supplies_stock(args)
        if name == "update_supply_quantity":
             # Auto-map common names
             key = args.get("item_key", "").lower()
             if "aguja" in key or "needle" in key: key = "supplies_needles"
             elif "sensor" in key: key = "supplies_sensors"
             elif "reser" in key: key = "supplies_reservoirs"
             
             # Fallback if no mapping needed or unknown
             args["item_key"] = key
             return await update_supply_quantity(args)
    except ValidationError as exc:
        return ToolError(type="validation_error", message=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.exception("Tool execution failed")
        return ToolError(type="runtime_error", message=str(exc))
    return ToolError(type="unknown_tool", message=name)
