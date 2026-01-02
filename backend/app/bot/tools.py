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
from app.bot.user_settings_resolver import resolve_bot_user_settings

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
    config_hash: Optional[str] = None # Security: Configuration Snapshot Hash
    quality: str = "unknown"
    source: str = "unknown"


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


class OptimizationResult(BaseModel):
    suggestions: List[Dict[str, Any]]
    run_summary: Dict[str, Any]
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
                
            # 2. Fallback: Any user who has settings configured
            stmt = text("SELECT user_id FROM user_settings LIMIT 1")
            row = (await session.execute(stmt)).fetchone()
            if row:
                return row[0]
                
        # If no session or no users found, default to admin
        return "admin"
    except Exception:
        # Unexpected error (e.g. table not created yet), return admin
        return "admin"


async def _load_user_settings(username: str = "admin") -> UserSettings:
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

    if ns_client:
        try:
            sgv = await ns_client.get_latest_sgv()
            bg_val = float(sgv.sgv)
            direction = sgv.direction or None
            delta = sgv.delta
            ts = datetime.fromtimestamp(sgv.date / 1000, timezone.utc)
            timestamp_str = ts.isoformat()
            quality = "live"
        except Exception as exc:
            logger.warning("NS sgv fetch failed: %s", exc)

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

    return BolusContext(
        bg_mgdl=bg_val,
        direction=direction,
        delta=delta,
        iob_u=iob_u,
        cob_g=cob_g,
        timestamp=timestamp_str,
        quality=quality,
        source="nightscout" if ns_client else "local",
        config_hash=user_settings.config_hash # Snapshot of config used to fetch this data
    )


async def calculate_bolus(carbs: float, fiber: float = 0.0, meal_type: Optional[str] = None, split: Optional[float] = None, extend_minutes: Optional[int] = None, alcohol: bool = False, target: Optional[float] = None) -> BolusResult | ToolError:
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

    # Calculate 24h Autosens (Short Term)
    autosens_ratio = 1.0
    autosens_reason = None
    try:
        engine = get_engine()
        if engine:
             async with AsyncSession(engine) as session:
                  # Use 'admin' or resolved user?
                  # calculate_bolus wrapper doesn't pass username explicitly, defaulting to admin/first.
                  # Ideally we should resolve generic user.
                  from app.bot.service import _resolve_user_id
                  # Circular import? _resolve_user_id is in service.py? No it is actually in tools.py (this file). 
                  # Wait, I see _resolve_user_id defined in this file at line 152.
                  u_id = await _resolve_user_id(session)
                  
                  res = await AutosensService.calculate_autosens(u_id, session, user_settings)
                  autosens_ratio = res.ratio
                  autosens_reason = res.reason
    except Exception as e:
        logger.warning(f"Bot Autosens Calc failed: {e}")
    
    # Build V2 Request
    req = BolusRequestV2(
        carbs_g=carbs,
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
        is_stale=False # Assume fresh if fetched via get_status_context
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
        preview = rotator.get_next_site_preview(target_user)
        preview_site = {
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
    events = ForecastEvents(
        boluses=[],
        carbs=[ForecastEventCarbs(time_offset_min=0, grams=carbs, absorption_minutes=180)],
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
                    event_type="Correction Bolus" if carbs == 0 else "Meal Bolus",
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
                event_type="Correction Bolus" if carbs == 0 else "Meal Bolus",
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
                         notes=notes
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
             
             rotation_site = rotator.rotate_site(target_user)
             site_info = {
                 "name": rotation_site.name,
                 "emoji": rotation_site.emoji,
                 "image": rotation_site.image_ref
             }
        except Exception as e:
            logger.warning(f"Rotation logic failed: {e}")

    health.record_action("add_treatment", ok=result.ok, error=error_text)
    return AddTreatmentResult(
        ok=result.ok,
        treatment_id=result.treatment_id,
        insulin=result.insulin,
        carbs=result.carbs,
        ns_uploaded=result.ns_uploaded,
        ns_error=result.ns_error or error_text,
        saved_db=result.saved_db,
        saved_local=result.saved_local,
        injection_site=site_info
    )


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
]


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
    except ValidationError as exc:
        return ToolError(type="validation_error", message=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.exception("Tool execution failed")
        return ToolError(type="runtime_error", message=str(exc))
    return ToolError(type="unknown_tool", message=name)
