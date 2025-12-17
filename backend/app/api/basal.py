from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
import uuid

import httpx
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field, root_validator, validator

from app.core.security import auth_required
from app.services import basal_repo

router = APIRouter()

# Hotfix for imports inside function to avoid circles or ensure readiness
from app.core.security import CurrentUser, get_current_user, require_admin

@router.post("/trigger-autoscan")
async def trigger_autoscan_manual(
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Manually triggers the daily night scan (for all users).
    Useful if the scheduled task was missed due to server sleep.
    """
    # Import here to avoid circulars
    from app.jobs import run_auto_night_scan
    await run_auto_night_scan()
    return {"ok": True, "message": "Autoscan triggered"}


# --- Schemas ---

class BasalDoseCreate(BaseModel):
    dose_u: Optional[float] = None
    dose_units: Optional[float] = None
    effective_from: Optional[date] = None
    created_at: Optional[datetime] = None

    @root_validator(pre=True)
    def check_dose_alias(cls, values):
        # Allow dose_units as alias for dose_u
        if values.get('dose_units') is not None and values.get('dose_u') is None:
            values['dose_u'] = values['dose_units']
        return values

    @validator('dose_u', always=True)
    def validate_dose_u(cls, v):
        if v is None:
            raise ValueError('dose_u is required')
        if v <= 0:
            raise ValueError('dose_u must be greater than 0')
        return v
    
class BasalDoseResponse(BaseModel):
    dose_u: float
    effective_from: date
    created_at: datetime

class HistoryItem(BaseModel):
    effective_from: date
    dose_u: float
    created_at: Optional[datetime] = None

class HistoryResponse(BaseModel):
    days: int
    items: List[HistoryItem]

class CheckinRequest(BaseModel):
    nightscout_url: Optional[str] = None
    nightscout_token: Optional[str] = None
    manual_bg: Optional[float] = None
    manual_trend: Optional[str] = None
    created_at: Optional[datetime] = None
    units: str = "mgdl"

class HistoricCheckin(BaseModel):
    date: date
    bg: float
    trend: Optional[str]

class CheckinResponse(BaseModel):
    bg_now_mgdl: float
    bg_age_min: Optional[int]
    trend: Optional[str]
    last3: List[HistoricCheckin] = []
    signal: Optional[str] = None

class ActiveResponse(BaseModel):
    dose_u: float
    started_at: datetime
    elapsed_h: float
    remaining_h: float
    remaining_u: float
    note: str

class NightScanRequest(BaseModel):
    nightscout_url: str
    nightscout_token: Optional[str] = None
    target_date: Optional[date] = None

class EvaluateChangeRequest(BaseModel):
    days: int = 7

# --- Endpoints ---

@router.post("/dose", response_model=BasalDoseResponse)
async def log_dose(
    payload: BasalDoseCreate,
    username: str = Depends(auth_required)
):
    """
    Registra una nueva dosis basal.
    """
    eff = payload.effective_from or date.today()
    # payload.dose_u is guaranteed not None by validator
    res = await basal_repo.upsert_basal_dose(username, payload.dose_u, eff, payload.created_at)
    
    # Defensive handling if DB returns None (shouldn't happen but handles the reported error)
    saved_dose = res.get("dose_u") if res else None
    
    # Fallback to payload if DB return missing
    if saved_dose is None:
        saved_dose = payload.dose_u

    # Final safety check
    if saved_dose is None:
        raise HTTPException(status_code=500, detail="Error saving basal dose: dose value missing")
        
    saved_eff = res.get("effective_from") if res else eff
    
    # Logic for created_at fallback
    if res and res.get("created_at"):
        saved_created = res["created_at"]
    elif payload.created_at:
        saved_created = payload.created_at
    else:
        saved_created = datetime.utcnow()

    return BasalDoseResponse(
        dose_u=float(saved_dose),
        effective_from=saved_eff,
        created_at=saved_created
    )

@router.post("/entry", response_model=BasalDoseResponse)
async def create_entry(
    payload: BasalDoseCreate,
    username: str = Depends(auth_required)
):
    """
    Alias para /dose (para compatibilidad con frontend).
    """
    return await log_dose(payload, username)

class LatestBasalResponse(BaseModel):
    dose_u: Optional[float] = None
    effective_from: Optional[date] = None
    created_at: Optional[datetime] = None

# ...

@router.get("/latest", response_model=LatestBasalResponse)
async def get_latest_basal_root(username: str = Depends(auth_required)):
    """
    Devuelve la última dosis registrada.
    """
    res = await basal_repo.get_latest_basal_dose(username)
    if not res:
        return LatestBasalResponse(
            dose_u=None,
            effective_from=None,
            created_at=None
        )
    
    return LatestBasalResponse(
        dose_u=float(res.get("dose_u") or 0.0),
        effective_from=res["effective_from"],
        created_at=res["created_at"]
    )

@router.get("/history", response_model=HistoryResponse)
async def get_basal_history(
    days: int = Query(30, ge=1, le=365),
    username: str = Depends(auth_required)
):
    """
    Devuelve historial de dosis basal.
    """
    items = await basal_repo.get_dose_history(username, days=days)
    formatted_items = [
        HistoryItem(
            effective_from=item['effective_from'],
            dose_u=float(item.get('dose_u') or 0.0),
            created_at=item.get('created_at')
        )
        for item in items
    ]
    return HistoryResponse(days=days, items=formatted_items)


@router.get("/dose/latest", response_model=Optional[BasalDoseResponse])
async def get_latest_dose(username: str = Depends(auth_required)):
    """
    Devuelve la configuración de basal más reciente (Legacy/Alias).
    """
    return await get_latest_basal_root(username)


@router.post("/checkin", response_model=CheckinResponse)
async def create_checkin(
    payload: CheckinRequest,
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Obtiene BG de Nightscout, guarda check-in diario y analiza tendencia.
    """
    # 1. Determine Source
    bg_val = 0.0
    age_min = 0
    direction = ""
    timestamp = None
    source = "nightscout"

    if payload.manual_bg is not None:
        # Manual Entry
        bg_val = payload.manual_bg
        direction = payload.manual_trend or ""
        # Use provided time or now. logic below uses timestamp (ms) for age calc.
        dt = payload.created_at or datetime.utcnow()
        timestamp = dt.timestamp() * 1000
        source = "manual"
    elif payload.nightscout_url:
        # Fetch from Nightscout
        from app.services.nightscout_client import NightscoutClient, NightscoutError, NightscoutSGV
        
        # Init client (it handles token/secret headers internally)
        ns_client = NightscoutClient(
            base_url=payload.nightscout_url,
            token=payload.nightscout_token
        )
        
        try:
            # Re-use known working method: get_latest_sgv() calls /api/v1/entries/sgv.json?count=1
            sgv_data: NightscoutSGV = await ns_client.get_latest_sgv()
            
            # sgv_data is a Pydantic model
            bg_val = float(sgv_data.sgv)
            direction = sgv_data.direction or ""
            timestamp = sgv_data.date # milliseconds
            
            now_ms = datetime.utcnow().timestamp() * 1000
            age_min = int((now_ms - timestamp) / 60000) if timestamp else 0
            
        except NightscoutError as ne:
            raise HTTPException(status_code=400, detail=f"Nightscout Error: {str(ne)}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Unexpected Error fetching BG: {str(e)}")
        finally:
            await ns_client.aclose()
    else:
        # Fallback: Check DB for config
        from app.services.nightscout_secrets_service import get_ns_config
        ns_config = await get_ns_config(db, username)
        
        if ns_config and ns_config.enabled and ns_config.url:
            from app.services.nightscout_client import NightscoutClient, NightscoutError, NightscoutSGV
            ns_client = NightscoutClient(base_url=ns_config.url, token=ns_config.api_secret)
            try:
                sgv_data: NightscoutSGV = await ns_client.get_latest_sgv()
                bg_val = float(sgv_data.sgv)
                direction = sgv_data.direction or ""
                timestamp = sgv_data.date
                
                now_ms = datetime.utcnow().timestamp() * 1000
                age_min = int((now_ms - timestamp) / 60000) if timestamp else 0
            except Exception as e:
                # If auto-fetch fails, we return error so client can prompt manual
                raise HTTPException(status_code=400, detail=f"Error fetching from stored Nightscout: {str(e)}")
            finally:
                await ns_client.aclose()
        else:
            raise HTTPException(status_code=400, detail="Must provide Nightscout URL or Manual BG (No config found)")

    # 2. Save Checkin
    checkin_date = date.today()
    if timestamp:
        # Simple convert to date (UTC)
        checkin_date = datetime.fromtimestamp(timestamp / 1000).date()

    await basal_repo.upsert_daily_checkin(
        username,
        checkin_date,
        bg_val,
        direction,
        age_min,
        source
    )

    # 3. Analyze Trend (Last 7 checkins)
    history = await basal_repo.list_checkins(username, days=7)
    last3_raw = history[:3]
    
    last3_formatted = []
    consecutive_high = 0
    TARGET = 110
    THRESHOLD = 20
    
    for c in last3_raw:
        val = float(c["bg_mgdl"])
        if val > (TARGET + THRESHOLD):
            consecutive_high += 1
        
        last3_formatted.append(HistoricCheckin(
            date=c.get("checkin_date") or c.get("day"),
            bg=val,
            trend=c.get("trend")
        ))
        
    signal = None
    if consecutive_high >= 3:
        signal = "BG matinal elevada en los últimos 3 registros. Considera revisarlo con tu endocrino."

    return CheckinResponse(
        bg_now_mgdl=bg_val,
        bg_age_min=age_min,
        trend=direction,
        last3=last3_formatted,
        signal=signal
    )


@router.get("/checkins")
async def get_checkins(
    days: int = 14,
    username: str = Depends(auth_required)
):
    history = await basal_repo.list_checkins(username, days=days)
    return history


@router.get("/active", response_model=ActiveResponse)
async def get_active_basal(username: str = Depends(auth_required)):
    """
    Calcula basal activa (IOB basal) estimación lineal 24h.
    """
    latest = await basal_repo.get_latest_basal_dose(username)
    if not latest:
        # Default placeholder
        return ActiveResponse(
            dose_u=0,
            started_at=datetime.utcnow(),
            elapsed_h=0,
            remaining_h=0,
            remaining_u=0,
            note="No hay dosis registrada."
        )

    start_dt = latest["created_at"]
    # Ensure TZ-naive for calculation if needed, or TZ-aware
    now = datetime.utcnow()
    
    # Handle asyncpg aware datetime
    if start_dt.tzinfo:
        start_dt = start_dt.replace(tzinfo=None) # naive UTC
    
    diff = now - start_dt
    elapsed_h = diff.total_seconds() / 3600.0
    
    duration = 24.0
    remaining_pct = max(0.0, 1.0 - (elapsed_h / duration))
    dose_val = float(latest.get("dose_u") or 0.0)
    remaining_u = dose_val * remaining_pct
    
    return ActiveResponse(
        dose_u=dose_val,
        started_at=start_dt,
        elapsed_h=elapsed_h,
        remaining_h=max(0.0, duration - elapsed_h),
        remaining_u=remaining_u,
        note=latest.get("note") or ""
    )

# --- Imports ---
from app.services import basal_repo, basal_engine
from app.core.db import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.nightscout_client import NightscoutClient

# ... (Previous endpoints like /dose, /history, /checkin kept as is logic-wise, assuming checking calls repo correctly)

# New Schema for Timeline
class TimelineItem(BaseModel):
    date: date
    dose_u: Optional[float]
    wake_bg: Optional[float]
    wake_trend: Optional[str]
    night_had_hypo: Optional[bool]
    night_min_bg: Optional[float]
    night_events_below_70: int

class TimelineResponse(BaseModel):
    days: int
    items: List[TimelineItem]
    data_quality: dict

# Updated Advice Response
class BasalAdviceResponseV2(BaseModel):
    message: str
    confidence: str # high/medium/low
    stats: dict

# Evaluation Response
class BasalEvaluationResponse(BaseModel):
    result: str
    summary: str
    evidence: dict

# --- Endpoints ---

@router.post("/night-scan", response_model=dict)
async def scan_night_endpoint(
    payload: NightScanRequest,
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Escanea Nightscout (00:00-06:00).
    """
    target_date = payload.target_date or date.today()
    
    # Secure Store Lookup
    from app.services.nightscout_secrets_service import get_ns_config
    ns_config = await get_ns_config(db, username)
    
    ns_url = None
    ns_token = None
    
    # Priority: DB Config > Payload Config
    if ns_config and ns_config.enabled and ns_config.url:
        ns_url = ns_config.url
        ns_token = ns_config.api_secret
    else:
        # Fallback
        ns_url = payload.nightscout_url
        ns_token = payload.nightscout_token

    if not ns_url:
        raise HTTPException(status_code=400, detail="Nightscout no configurado. Ve a Ajustes > Nightscout y guarda tus credenciales.")

    try:
        ns_client = NightscoutClient(
            base_url=ns_url,
            token=ns_token
        )
        try:
             result = await basal_engine.scan_night_service(username, target_date, ns_client, db)
             return result
        finally:
             await ns_client.aclose()
    except Exception as e:
         raise HTTPException(status_code=400, detail=str(e))

@router.get("/timeline", response_model=TimelineResponse)
async def get_timeline(
    days: int = 14,
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    return await basal_engine.get_timeline_service(username, days, db)

@router.get("/advice", response_model=BasalAdviceResponseV2)
async def get_basal_advice(
    days: int = 3,
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Advice v2 with confidence.
    """
    return await basal_engine.get_advice_service(username, days, db)

@router.post("/evaluate-change", response_model=BasalEvaluationResponse)
async def evaluate_change(
    payload: EvaluateChangeRequest,
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    res = await basal_engine.evaluate_change_service(username, payload.days, db)
    return res

