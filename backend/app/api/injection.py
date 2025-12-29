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
    bolus: str # "zone:point" e.g. "abd_l_top:1"
    basal: str 

class RotateRequest(BaseModel):
    type: str # "bolus" (rapid) or "basal"
    target: Optional[str] = None # Optional manual override

@router.get("/state", response_model=InjectionStateResponse)
def get_injection_state(store: DataStore = Depends(get_store), _: str = Depends(auth_required)):
    """Fetch current global injection state (the truth)."""
    mgr = InjectionManager(store)
    # We must map the simple index-based backend logic to the frontend "id" logic if they differ.
    # Frontend uses: "abd_l_top:1"
    # Backend currently just returns: "Abdomen Derecha (Superior)" string.
    # WE NEED TO UNIFY THIS.
    # Let's fix backend to use frontend IDs logic or vice versa.
    # For now, let's assume we return raw IDs and Frontend consumes them.
    # But wait, backend service implemented simple strings.
    # We need to Upgrade the backend service to match frontend IDs.
    
    # Actually, let's just expose what the backend has, but the user wants synchronization.
    # Synchronization means Frontend reads from Backend.
    
    # Let's pivot: Backend needs to store the "zone:point" ID, not just a label.
    
    state = mgr._load_state()
    bolus_id = state.get("bolus", {}).get("last_used_id", "abd_l_top:1")
    basal_id = state.get("basal", {}).get("last_used_id", "leg_right:1")
    
    return InjectionStateResponse(bolus=bolus_id, basal=basal_id)

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
