from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from app.core.security import auth_required
from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.injection_sites import InjectionManager
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
def get_injection_state(store: DataStore = Depends(get_store), _: str = Depends(auth_required)):
    """Fetch current global injection state (the truth)."""
    mgr = InjectionManager(store)
    
    state = mgr._load_state()
    bolus_id = state.get("bolus", {}).get("last_used_id", "abd_l_top:1")
    basal_id = state.get("basal", {}).get("last_used_id", "leg_right:1")
    
    # Calculate Next explicitly to ensure frontend sync with Bot
    try:
        n_bolus = mgr.get_next_site("bolus")
        n_basal = mgr.get_next_site("basal")
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
def rotate_injection_site(payload: RotateRequest, store: DataStore = Depends(get_store), _: str = Depends(auth_required)):
    """Frontend notifies backend of a rotation (manual selection or auto)."""
    mgr = InjectionManager(store)
    
    if payload.target:
        # Manual Force
        mgr.set_current_site(payload.type, payload.target)
    else:
        # Auto Rotate
        mgr.rotate_site(payload.type)
        
    return {"status": "ok"}
