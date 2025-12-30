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
from app.services.bolus import recommend_bolus, BolusRequestData
from app.services.forecast_engine import ForecastEngine
from app.models.forecast import (
    ForecastSimulateRequest,
    ForecastEvents,
    ForecastEventBolus,
    ForecastEventCarbs,
    SimulationParams,
    MomentumConfig,
)
from app.models.settings import UserSettings
from app.services.treatment_logger import log_treatment

logger = logging.getLogger(__name__)


class ToolError(BaseModel):
    type: str
    message: str


class StatusContext(BaseModel):
    bg_mgdl: Optional[float] = None
    direction: Optional[str] = None
    delta: Optional[float] = None
    iob_u: Optional[float] = None
    cob_g: Optional[float] = None
    timestamp: Optional[str] = None
    quality: str = "unknown"
    source: str = "unknown"


class BolusResult(BaseModel):
    units: float
    explanation: List[str]
    confidence: str = "high"
    quality: str = "ok"


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
    sample_size: int = 0
    quality: str = "unknown"


class TempMode(BaseModel):
    mode: str = Field(..., pattern="^(sport|sick|normal)$")
    expires_minutes: int = Field(default=180, ge=15, le=720)
    note: Optional[str] = None


class AddTreatmentRequest(BaseModel):
    carbs: Optional[float] = None
    insulin: Optional[float] = None
    notes: Optional[str] = None


class AddTreatmentResult(BaseModel):
    ok: bool
    treatment_id: Optional[str] = None
    insulin: Optional[float] = None
    carbs: Optional[float] = None
    ns_uploaded: Optional[bool] = None
    ns_error: Optional[str] = None
    saved_db: Optional[bool] = None
    saved_local: Optional[bool] = None


def _build_ns_client(settings: UserSettings | None) -> Optional[NightscoutClient]:
    if not settings or not settings.nightscout.url:
        return None
    return NightscoutClient(
        base_url=settings.nightscout.url,
        token=settings.nightscout.token,
        timeout_seconds=10,
    )


async def _load_user_settings(username: str = "admin") -> UserSettings:
    user_settings = None

    # 1. Try DB First (Source of Truth for General Config)
    try:
        from app.core.db import get_engine, AsyncSession
        from app.services.settings_service import get_user_settings_service
        
        engine = get_engine()
        if engine:
            async with AsyncSession(engine) as session:
                db_res = await get_user_settings_service(username, session)
                if db_res and db_res.get("settings"):
                    user_settings = UserSettings.migrate(db_res["settings"])
    except Exception as e:
        logger.warning(f"DB Settings load failed for {username}, falling back to file: {e}")

    # 2. Fallback to File (Legacy / Offline)
    if not user_settings:
        settings = get_settings()
        store = DataStore(Path(settings.data.data_dir))
        user_settings = store.load_settings(username)
    
    # 3. Hybrid Overlay: ALWAYS try to get NS secrets from DB (Source of Truth for Secrets)
    # The general settings blob might have empty/outdated NS config.
    try:
        from app.services.nightscout_secrets_service import get_ns_config
        from app.core.db import get_engine, AsyncSession
        engine = get_engine()
        if engine:
             async with AsyncSession(engine) as session:
                 ns_conf = await get_ns_config(session, username)
                 if ns_conf:
                      user_settings.nightscout.url = ns_conf.url
                      user_settings.nightscout.token = ns_conf.api_secret
    except Exception as e:
        logger.warning(f"Failed to overlay DB settings for {username}: {e}")
        
    return user_settings


async def get_status_context(username: str = "admin", user_settings: Optional[UserSettings] = None) -> StatusContext | ToolError:
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

    return StatusContext(
        bg_mgdl=bg_val,
        direction=direction,
        delta=delta,
        iob_u=iob_u,
        cob_g=cob_g,
        timestamp=timestamp_str,
        quality=quality,
        source="nightscout" if ns_client else "local",
    )


async def calculate_bolus(carbs: float, meal_type: Optional[str] = None, split: Optional[float] = None, extend_minutes: Optional[int] = None) -> BolusResult | ToolError:
    try:
        user_settings = await _load_user_settings()
    except Exception as exc:
        return ToolError(type="config_error", message=f"Config no disponible: {exc}")

    status = await get_status_context(user_settings=user_settings)
    if isinstance(status, ToolError):
        return status

    if meal_type:
        meal_slot = meal_type
    else:
        # Infer from system local time using User Settings Schedule
        h = datetime.now().hour
        sch = user_settings.schedule
        
        if sch.breakfast_start_hour <= h < sch.lunch_start_hour:
            meal_slot = "breakfast"
        elif sch.lunch_start_hour <= h < sch.dinner_start_hour:
             meal_slot = "lunch"
        else:
             meal_slot = "dinner"
    now_utc = datetime.now(timezone.utc)
    try:
        iob_u = status.iob_u or 0.0
    except Exception:
        iob_u = 0.0
    bg_val = status.bg_mgdl or user_settings.targets.mid

    req = BolusRequestData(carbs_g=carbs, bg_mgdl=bg_val, meal_slot=meal_slot, target_mgdl=user_settings.targets.mid)
    rec = recommend_bolus(req, user_settings, iob_u)
    explain = rec.explain
    if split or extend_minutes:
        explain.append("Solicitud de bolo extendido/dual registrada. Confirmar manualmente en bomba.")
    return BolusResult(units=rec.upfront_u, explanation=explain, confidence="high", quality="data-driven")


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
    cf = user_settings.cf.lunch
    correction_units = max((bg - target) / cf - iob, 0.0)
    explanation = [
        f"BG {bg} vs objetivo {target} con CF {cf}",
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
        carbs=[ForecastEventCarbs(time_offset_min=0, grams=carbs, absorption_minutes=user_settings.iob.carb_absorption_minutes if hasattr(user_settings, "iob") else 180)],
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
    lows = sum(1 for v in values if v < 70)
    highs = sum(1 for v in values if v > 250)
    tir = sum(1 for v in values if 70 <= v <= 180) / len(values) * 100
    avg = sum(values) / len(values)
    return NightscoutStats(range_hours=range_hours, avg_bg=avg, tir_pct=tir, lows=lows, highs=highs, sample_size=len(values), quality="live")


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
    )


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
                "mode": {"type": "STRING", "enum": ["sport", "sick", "normal"]},
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
            },
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
                meal_type=args.get("meal_type"),
                split=args.get("split"),
                extend_minutes=args.get("extend_minutes"),
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
    except ValidationError as exc:
        return ToolError(type="validation_error", message=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.exception("Tool execution failed")
        return ToolError(type="runtime_error", message=str(exc))
    return ToolError(type="unknown_tool", message=name)
