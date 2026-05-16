from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.security import CurrentUser
from app.core.settings import Settings, get_settings
from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2
from app.models.settings import UserSettings
from app.services.bolus_calc_service import calculate_bolus_stateless_service
from app.services.iob import compute_cob_from_sources, compute_iob_from_sources
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.services.settings_service import get_user_settings_service
from app.services.store import DataStore

router = APIRouter()

AGENT_USERNAME = "admin"
SAFE_MODE = "read_only_estimate_only"
VALID_INSTANCE_ROLES = {"primary", "backup", "unknown"}
VALID_INSTANCE_LOCATIONS = {"nas", "render", "local", "unknown"}


class AgentStatusResponse(BaseModel):
    ok: bool
    version: str
    environment: str
    timestamp: datetime
    safe_mode: str
    agent_api_enabled: bool
    instance_role: str
    instance_location: str
    emergency_mode: bool
    nightscout: dict[str, Any]
    dexcom: dict[str, Any]


class AgentGlucoseCurrentResponse(BaseModel):
    glucose_mgdl: Optional[float] = None
    trend: Optional[str] = None
    timestamp: Optional[datetime] = None
    source: str
    unit: str = "mg/dL"
    age_minutes: Optional[float] = None
    stale: bool = False
    available: bool = False
    warnings: list[str] = Field(default_factory=list)


class AgentContextResponse(BaseModel):
    timestamp: datetime
    safe_mode: str
    glucose: AgentGlucoseCurrentResponse
    iob_u: Optional[float] = None
    cob_g: Optional[float] = None
    last_meal: Optional[dict[str, Any]] = None
    nightscout: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


class AgentBolusEstimateResponse(BaseModel):
    estimation: BolusResponseV2
    explanation: list[str]
    warnings: list[str]
    confidence: Optional[float] = None
    forecast_curve: Optional[list[dict[str, Any]]] = None
    persisted: bool = False
    nightscout_uploaded: bool = False


def _agent_token() -> Optional[str]:
    token = os.environ.get("AGENT_API_TOKEN")
    return token.strip() if token and token.strip() else None


def _allowed_ips() -> set[str]:
    raw = os.environ.get("AGENT_ALLOWED_IPS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _normalized_env_choice(key: str, allowed_values: set[str]) -> str:
    value = os.environ.get(key)
    if not value or not value.strip():
        return "unknown"
    normalized = value.strip().lower()
    return normalized if normalized in allowed_values else "unknown"


def _instance_metadata() -> tuple[str, str, bool]:
    role = _normalized_env_choice("APP_INSTANCE_ROLE", VALID_INSTANCE_ROLES)
    location = _normalized_env_choice("APP_INSTANCE_LOCATION", VALID_INSTANCE_LOCATIONS)
    emergency_mode = role == "backup"
    return role, location, emergency_mode


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))


async def require_agent_access(request: Request) -> None:
    expected = _agent_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent API disabled: AGENT_API_TOKEN is not configured",
        )

    allowed_ips = _allowed_ips()
    client_host = request.client.host if request.client else None
    if allowed_ips and client_host not in allowed_ips:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP not allowed")

    auth = request.headers.get("authorization", "")
    scheme, _, supplied = auth.partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid agent token")


async def _load_user_settings(session: AsyncSession, store: DataStore) -> UserSettings:
    try:
        data = await get_user_settings_service(AGENT_USERNAME, session)
        if data and data.get("settings"):
            return UserSettings.migrate(data["settings"])
    except Exception:
        pass
    return store.load_settings()




async def _last_meal(session: AsyncSession) -> Optional[dict[str, Any]]:
    try:
        from sqlalchemy import select

        from app.models.treatment import Treatment

        stmt = (
            select(Treatment)
            .where(Treatment.user_id == AGENT_USERNAME)
            .where(Treatment.carbs > 0)
            .order_by(Treatment.created_at.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalars().first()
        if not row:
            return None
        return {
            "created_at": row.created_at,
            "carbs_g": float(row.carbs or 0),
            "fat_g": float(row.fat or 0),
            "protein_g": float(row.protein or 0),
            "fiber_g": float(row.fiber or 0),
            "carb_profile": row.carb_profile,
        }
    except Exception:
        return None

async def _build_ns_client(session: AsyncSession) -> tuple[Optional[NightscoutClient], dict[str, Any]]:
    ns_state: dict[str, Any] = {"enabled": False, "configured": False, "reachable": None}
    ns_config = await get_ns_config(session, AGENT_USERNAME)
    if ns_config and ns_config.enabled and ns_config.url:
        ns_state.update({"enabled": True, "configured": True})
        return NightscoutClient(ns_config.url, ns_config.api_secret, timeout_seconds=5), ns_state
    return None, ns_state


async def _current_glucose(session: AsyncSession) -> AgentGlucoseCurrentResponse:
    client, _ = await _build_ns_client(session)
    if client is None:
        return AgentGlucoseCurrentResponse(source="none", warnings=["Nightscout no configurado"])

    try:
        sgv = await client.get_latest_sgv()
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        age_minutes = max(0.0, (now_ms - sgv.date) / 60000.0)
        return AgentGlucoseCurrentResponse(
            glucose_mgdl=float(sgv.sgv),
            trend=sgv.direction,
            timestamp=datetime.fromtimestamp(sgv.date / 1000, tz=timezone.utc),
            source="nightscout",
            age_minutes=age_minutes,
            stale=age_minutes > 10,
            available=True,
            warnings=["Glucosa obsoleta (>10 min)"] if age_minutes > 10 else [],
        )
    except Exception as exc:
        return AgentGlucoseCurrentResponse(
            source="nightscout",
            warnings=[f"No se pudo obtener glucosa actual: {exc.__class__.__name__}"],
        )
    finally:
        await client.aclose()


@router.get("/status", response_model=AgentStatusResponse)
async def agent_status(
    _: None = Depends(require_agent_access),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AgentStatusResponse:
    ns_config = await get_ns_config(session, AGENT_USERNAME)
    nightscout = {
        "configured": bool(ns_config and ns_config.enabled and ns_config.url),
        "enabled": bool(ns_config and ns_config.enabled),
        "reachable": None,
    }
    dexcom = {
        "configured": bool(settings.dexcom.enabled and settings.dexcom.username),
        "enabled": bool(settings.dexcom.enabled),
    }
    instance_role, instance_location, emergency_mode = _instance_metadata()
    return AgentStatusResponse(
        ok=True,
        version="0.1.0",
        environment=os.environ.get("ENV", os.environ.get("ENVIRONMENT", "unknown")),
        timestamp=datetime.now(timezone.utc),
        safe_mode=SAFE_MODE,
        agent_api_enabled=True,
        instance_role=instance_role,
        instance_location=instance_location,
        emergency_mode=emergency_mode,
        nightscout=nightscout,
        dexcom=dexcom,
    )


@router.get("/glucose/current", response_model=AgentGlucoseCurrentResponse)
async def agent_current_glucose(
    _: None = Depends(require_agent_access),
    session: AsyncSession = Depends(get_db_session),
) -> AgentGlucoseCurrentResponse:
    return await _current_glucose(session)


@router.get("/context", response_model=AgentContextResponse)
async def agent_context(
    _: None = Depends(require_agent_access),
    session: AsyncSession = Depends(get_db_session),
    store: DataStore = Depends(_data_store),
) -> AgentContextResponse:
    warnings: list[str] = []
    glucose = await _current_glucose(session)
    warnings.extend(glucose.warnings)

    user_settings = await _load_user_settings(session, store)
    ns_client, ns_state = await _build_ns_client(session)
    iob_u = None
    cob_g = None
    try:
        iob_u, _, iob_info, iob_warning = await compute_iob_from_sources(
            datetime.now(timezone.utc),
            user_settings,
            ns_client,
            store,
            user_id=AGENT_USERNAME,
        )
        cob_g, cob_info, _ = await compute_cob_from_sources(
            datetime.now(timezone.utc),
            ns_client,
            store,
            user_id=AGENT_USERNAME,
        )
        if iob_warning:
            warnings.append(iob_warning)
        if iob_info and iob_info.status not in {"ok", "partial"}:
            warnings.append(f"IOB status: {iob_info.status}")
        if cob_info and cob_info.status not in {"ok", "partial"}:
            warnings.append(f"COB status: {cob_info.status}")
    except Exception as exc:
        warnings.append(f"No se pudo calcular IOB/COB: {exc.__class__.__name__}")
    finally:
        if ns_client:
            await ns_client.aclose()

    return AgentContextResponse(
        timestamp=datetime.now(timezone.utc),
        safe_mode=SAFE_MODE,
        glucose=glucose,
        iob_u=round(iob_u, 2) if iob_u is not None else None,
        cob_g=round(cob_g, 1) if cob_g is not None else None,
        nightscout=ns_state,
        warnings=warnings,
    )


@router.post("/bolus/estimate", response_model=AgentBolusEstimateResponse)
async def agent_bolus_estimate(
    payload: BolusRequestV2,
    _: None = Depends(require_agent_access),
    session: AsyncSession = Depends(get_db_session),
    store: DataStore = Depends(_data_store),
) -> AgentBolusEstimateResponse:
    response = await calculate_bolus_stateless_service(
        payload,
        store=store,
        user=CurrentUser(username=AGENT_USERNAME, role="agent"),
        session=session,
        persist_autosens_run=False,
        persist_iob_cache=False,
    )
    return AgentBolusEstimateResponse(
        estimation=response,
        explanation=response.explain,
        warnings=response.warnings,
        confidence=getattr(response, "confidence_score", None),
        forecast_curve=None,
        persisted=False,
        nightscout_uploaded=False,
    )
