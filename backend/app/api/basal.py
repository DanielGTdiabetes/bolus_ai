from datetime import datetime, date, timedelta
from typing import List, Optional
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.security import auth_required
from app.services import basal_repo

router = APIRouter()

# --- Schemas ---

class BasalDoseCreate(BaseModel):
    dose_u: float = Field(..., gt=0)
    effective_from: Optional[date] = None

class BasalDoseResponse(BaseModel):
    dose_u: float
    effective_from: date
    created_at: datetime

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
    res = await basal_repo.upsert_basal_dose(username, payload.dose_u, eff)
    return BasalDoseResponse(
        dose_u=float(res["dose_u"]),
        effective_from=res["effective_from"],
        created_at=res["created_at"]
    )


@router.get("/dose/latest", response_model=Optional[BasalDoseResponse])
async def get_latest_dose(username: str = Depends(auth_required)):
    """
    Devuelve la configuración de basal más reciente.
    """
    res = await basal_repo.get_latest_basal_dose(username)
    if not res:
        return None
    return BasalDoseResponse(
        dose_u=float(res["dose_u"]),
        effective_from=res["effective_from"],
        created_at=res["created_at"]
    )


@router.post("/checkin", response_model=CheckinResponse)
async def create_checkin(
    payload: CheckinRequest,
    username: str = Depends(auth_required)
):
    """
    Obtiene BG de Nightscout, guarda check-in diario y analiza tendencia.
    """
    # 1. Fetch from Nightscout
    ns_url = payload.nightscout_url.rstrip('/')
    url = f"{ns_url}/api/v1/entries/current.json"
    headers = {}
    if payload.nightscout_token:
        headers["Authorization"] = f"Bearer {payload.nightscout_token}"
    
    bg_val = 0.0
    age_min = 0
    direction = ""
    timestamp = None
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            
            sgv = data.get('sgv')
            direction = data.get('direction')
            timestamp = data.get('date') # ms
            
            if not sgv:
                raise ValueError("No SGV in response")
                
            now_ms = datetime.utcnow().timestamp() * 1000
            age_min = int((now_ms - timestamp) / 60000) if timestamp else 0
            bg_val = float(sgv)
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Nightscout Error: {str(e)}")

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
