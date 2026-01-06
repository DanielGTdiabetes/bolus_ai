from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from app.core.security import auth_required
from app.core.settings import get_settings
from app.services.async_injection_manager import AsyncInjectionManager
from pathlib import Path

router = APIRouter()

def get_store() -> DataStore:
    s = get_settings()
    return DataStore(Path(s.data.data_dir))

class InjectionStateResponse(BaseModel):
    bolus: str # "zone:point" e.g. "abd_l_top:1" (LAST USED)
    basal: str 
    next_bolus: Optional[str] = None # Calculated NEXT
    next_basal: Optional[str] = None

class RotateRequest(BaseModel):
    type: str # "bolus" (rapid) or "basal"
    target: Optional[str] = None # Optional manual override

@router.get("/state", response_model=InjectionStateResponse)
async def get_injection_state(_: str = Depends(auth_required)):
    """Fetch current global injection state (from DB)."""
    # Assume admin for single user app
    mgr = AsyncInjectionManager("admin")
    
    state = await mgr.get_state()
    bolus_id = state.get("bolus", {}).get("last_used_id", "abd_l_top:1")
    basal_id = state.get("basal", {}).get("last_used_id", "glute_right:1")
    
    # Calculate Next explicitly
    try:
        n_bolus = await mgr.get_next_site("bolus")
        n_basal = await mgr.get_next_site("basal")
        next_bolus_id = n_bolus["id"]
        next_basal_id = n_basal["id"]
    except:
        next_bolus_id = None
        next_basal_id = None
    
    return InjectionStateResponse(
        bolus=bolus_id, 
        basal=basal_id,
        next_bolus=next_bolus_id,
        next_basal=next_basal_id
    )

@router.post("/rotate")
async def rotate_injection_site(payload: RotateRequest, _: str = Depends(auth_required)):
    """Frontend notifies backend of a rotation (manual selection or auto)."""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API /rotate] Received request: type={payload.type}, target={payload.target}")
    
    mgr = AsyncInjectionManager("admin")
    
    kind = "bolus" if payload.type == "rapid" else payload.type
    
    if payload.target:
        # Manual Force
        logger.info(f"[API /rotate] Setting manual site: {kind} -> {payload.target}")
        await mgr.set_current_site(kind, payload.target)
    else:
        # Auto Rotate
        logger.info(f"[API /rotate] Auto rotating: {kind}")
        await mgr.rotate_site(kind)
    
    logger.info(f"[API /rotate] Done. Returning ok.")
    return {"status": "ok"}

@router.get("/rotate-legacy")
async def rotate_legacy(type: str, target: str, _: str = Depends(auth_required)):
    """Fallback GET endpoint."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[API /rotate-legacy] GET Request: type={type}, target={target}")
    
    mgr = AsyncInjectionManager("admin")
    kind = "bolus" if type == "rapid" else type
    await mgr.set_current_site(kind, target)
    return {"status": "ok", "method": "GET"}
