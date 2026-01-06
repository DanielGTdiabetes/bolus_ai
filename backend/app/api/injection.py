from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, Optional

from app.core.security import auth_required
from app.services.async_injection_manager import AsyncInjectionManager

router = APIRouter()

class InjectionPointState(BaseModel):
    insulin_type: str
    last_point_id: str
    suggested_point_id: Optional[str] = None
    source: str = "auto"
    updated_at: Optional[str] = None

class InjectionStateResponse(BaseModel):
    bolus: str 
    basal: str 
    next_bolus: Optional[str] = None 
    next_basal: Optional[str] = None
    states: Dict[str, InjectionPointState]

class ManualInjectionRequest(BaseModel):
    insulin_type: str = Field(pattern="^(basal|rapid|bolus)$")
    point_id: str

    @field_validator("insulin_type")
    @classmethod
    def _normalize_type(cls, v: str) -> str:
        val = v.lower()
        if val == "bolus":
            return "rapid"
        return val

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
        next_bolus_id = n_bolus["id"] if n_bolus else None
        next_basal_id = n_basal["id"] if n_basal else None
    except:
        next_bolus_id = None
        next_basal_id = None

    resp_states = {
        "bolus": {
            "insulin_type": "rapid",
            "last_point_id": bolus_id,
            "suggested_point_id": next_bolus_id,
            "source": state.get("bolus", {}).get("source", "auto"),
            "updated_at": state.get("bolus", {}).get("updated_at"),
        },
        "basal": {
            "insulin_type": "basal",
            "last_point_id": basal_id,
            "suggested_point_id": next_basal_id,
            "source": state.get("basal", {}).get("source", "auto"),
            "updated_at": state.get("basal", {}).get("updated_at"),
        }
    }

    return JSONResponse(content={
        "bolus": bolus_id, 
        "basal": basal_id,
        "next_bolus": next_bolus_id,
        "next_basal": next_basal_id,
        "states": resp_states,
        "source": resp_states.get("bolus", {}).get("source")  # legacy: keep a simple source key if used elsewhere
    })

@router.post("/manual")
async def set_manual_injection(payload: ManualInjectionRequest, _: str = Depends(auth_required)):
    """Persist manual selection of injection point."""
    import logging
    logger = logging.getLogger(__name__)

    mgr = AsyncInjectionManager("admin")
    kind = "bolus" if payload.insulin_type == "rapid" else payload.insulin_type

    try:
        normalized = await mgr.set_current_site(kind, payload.point_id, source="manual")
        state = await mgr.get_state()
        last_state = state.get(kind, {})
        suggested = None
        try:
            suggested_site = await mgr.get_next_site(kind)
            suggested = suggested_site.get("id") if suggested_site else None
        except Exception:
            suggested = None

        resp = {
            "ok": True,
            "insulin_type": payload.insulin_type,
            "point_id": normalized,
            "updated_at": last_state.get("updated_at"),
            "source": "manual",
            "suggested_point_id": suggested
        }
        logger.info(f"[API /manual] Set manual site {kind} -> {normalized}")
        return JSONResponse(content=resp)
    except ValueError as ve:
        logger.warning(f"[API /manual] Validation failed: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[API /manual] Error persisting manual selection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error saving manual site")

@router.post("/rotate")
async def rotate_injection_site(payload: RotateRequest, _: str = Depends(auth_required)):
    """Frontend notifies backend of an automatic rotation."""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[API /rotate] Received request: type={payload.type}, target={payload.target}")
    
    mgr = AsyncInjectionManager("admin")
    
    kind = "bolus" if payload.type == "rapid" else payload.type
    
    try:
        if payload.target:
            # Explicit rotate to target but marked as auto (back-compat)
            logger.info(f"[API /rotate] Setting site via rotate (auto source): {kind} -> {payload.target}")
            target_id = await mgr.set_current_site(kind, payload.target, source="auto")
        else:
            # Auto Rotate
            logger.info(f"[API /rotate] Auto rotating: {kind}")
            rotated = await mgr.rotate_site(kind)
            target_id = rotated.get("id") if rotated else None
            
        # VERIFICATION (Read-After-Write)
        verify_state = await mgr.get_state()
        saved_val = verify_state.get(kind, {}).get("last_used_id")
        
        logger.info(f"[API /rotate] VERIFY DB: Expected ~ {payload.target if payload.target else 'rotated'}, Got {saved_val}")
        
        if payload.target:
            normalized_target = target_id
            if saved_val != normalized_target:
                logger.error(f"❌ CRITICAL PERSISTENCE FAILURE. DB has {saved_val}, wanted {normalized_target}")
                raise HTTPException(status_code=500, detail=f"DB Write Failed. Got {saved_val}")

        logger.info(f"[API /rotate] Done. Persistence Verified.")
        
        resp = JSONResponse(content={
            "status": "ok",
            "verified": saved_val,
            "source": "auto",
            "insulin_type": payload.type,
            "point_id": saved_val
        })
        resp.headers["X-Persist-Status"] = "Verified"
        return resp

    except Exception as e:
        logger.error(f"Error in rotate endpoint: {e}", exc_info=True)
        return JSONResponse(content={"status": "error", "detail": str(e)}, status_code=500)

@router.get("/rotate-legacy")
async def rotate_legacy(type: str, target: str, _: str = Depends(auth_required)):
    """Fallback GET endpoint."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[API /rotate-legacy] GET Request: type={type}, target={target}")
    
    mgr = AsyncInjectionManager("admin")
    kind = "bolus" if type == "rapid" else type
    await mgr.set_current_site(kind, target, source="manual")
    return {"status": "ok", "method": "GET"}
