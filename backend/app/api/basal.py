from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
import uuid

import httpx
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, Field, root_validator, validator

from app.core.security import auth_required
from app.services import basal_repo

router = APIRouter()

# --- Schemas ---

class BasalDoseCreate(BaseModel):
    dose_u: Optional[float] = None
    dose_units: Optional[float] = None
    effective_from: Optional[date] = None

    @root_validator(pre=True)
    def check_dose_alias(cls, values):
        # Allow dose_units as alias for dose_u
        if values.get('dose_units') is not None and values.get('dose_u') is None:
            values['dose_u'] = values['dose_units']
        return values

    @validator('dose_u')
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

class HistoryResponse(BaseModel):
    days: int
    items: List[HistoryItem]

class CheckinRequest(BaseModel):
    nightscout_url: str
    nightscout_token: Optional[str] = None
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
    res = await basal_repo.upsert_basal_dose(username, payload.dose_u, eff)
    return BasalDoseResponse(
        dose_u=float(res["dose_u"]),
        effective_from=res["effective_from"],
        created_at=res["created_at"]
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

@router.get("/latest", response_model=Optional[BasalDoseResponse])
async def get_latest_basal_root(username: str = Depends(auth_required)):
    """
    Devuelve la última dosis registrada.
    """
    res = await basal_repo.get_latest_basal_dose(username)
    if not res:
        return None
    return BasalDoseResponse(
        dose_u=float(res["dose_u"]),
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
        HistoryItem(effective_from=item['effective_from'], dose_u=float(item['dose_u']))
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
    username: str = Depends(auth_required)
):
    """
    Obtiene BG de Nightscout, guarda check-in diario y analiza tendencia.
    """
    # 1. Fetch from Nightscout using robust Client
    from app.services.nightscout_client import NightscoutClient, NightscoutError, NightscoutSGV
    
    bg_val = 0.0
    age_min = 0
    direction = ""
    timestamp = None
    
    # Initialize client (it handles token/secret headers internally)
    # The client expects base_url and token.
    ns_client = NightscoutClient(
        base_url=payload.nightscout_url,
        token=payload.nightscout_token
    )
    
    try:
        # Re-use known working method: get_latest_sgv() calls /api/v1/entries/sgv.json?count=1
        sgv_data: NightscoutSGV = await ns_client.get_latest_sgv()
        
        # sgv_data is a Pydantic model: { sgv: int, direction: str, dateString: str, date: int, ... }
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
        "nightscout"
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
            date=c["day"],
            bg=val,
            trend=c["trend"]
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
    remaining_u = float(latest["dose_u"]) * remaining_pct
    
    return ActiveResponse(
        dose_u=float(latest["dose_u"]),
        started_at=start_dt,
        elapsed_h=round(elapsed_h, 2),
        remaining_h=round(max(0, duration - elapsed_h), 2),
        remaining_u=round(remaining_u, 2),
        note="Estimación lineal (24h) basada en la hora de registro."
    )
