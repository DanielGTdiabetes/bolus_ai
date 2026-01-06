from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, Optional, Literal, List

from app.core.security import auth_required
from app.services.async_injection_manager import AsyncInjectionManager

router = APIRouter()


class InjectionPointState(BaseModel):
    insulin_type: Literal["rapid", "basal"]
    last_point_id: Optional[str] = None
    suggested_point_id: Optional[str] = None
    source: Optional[str] = None
    updated_at: Optional[str] = None


class InjectionStateResponse(BaseModel):
    rapid: Optional[str] = None
    basal: Optional[str] = None
    next_rapid: Optional[str] = None
    next_basal: Optional[str] = None
    states: Dict[str, InjectionPointState]
    warnings: Optional[List[str]] = None
    source: Optional[str] = None


class InjectionMutationResponse(BaseModel):
    ok: bool
    insulin_type: Literal["rapid", "basal"]
    point_id: str
    updated_at: Optional[str] = None
    source: Literal["manual", "auto"]
    suggested_point_id: Optional[str] = None


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
    insulin_type: str = Field(pattern="^(basal|rapid|bolus)$", alias="type")  # "rapid" (bolus alias) or "basal"
    target: Optional[str] = None  # Optional manual override
    model_config = {"populate_by_name": True}

    @field_validator("insulin_type")
    @classmethod
    def _normalize_type(cls, v: str) -> str:
        val = v.lower()
        if val == "bolus":
            return "rapid"
        return val


async def _build_state_payload(mgr: AsyncInjectionManager) -> Dict[str, Any]:
    import logging

    logger = logging.getLogger(__name__)
    state = await mgr.get_state()
    rapid_state = state.get("rapid") or {}
    basal_state = state.get("basal") or {}

    rapid_id = rapid_state.get("last_used_id")
    basal_id = basal_state.get("last_used_id")
    warnings: List[str] = []

    if not rapid_id:
        warnings.append("rapid.last_used_id missing; returning null without default")
        logger.warning("[API /state] rapid last_used_id missing; returning null")
    if not basal_id:
        warnings.append("basal.last_used_id missing; returning null without default")
        logger.warning("[API /state] basal last_used_id missing; returning null")

    # Calculate Next explicitly
    try:
        n_rapid = await mgr.get_next_site("rapid")
        n_basal = await mgr.get_next_site("basal")
        next_rapid_id = n_rapid["id"] if n_rapid else None
        next_basal_id = n_basal["id"] if n_basal else None
    except Exception:
        next_rapid_id = None
        next_basal_id = None

    resp_states = {
        "rapid": {
            "insulin_type": "rapid",
            "last_point_id": rapid_id,
            "suggested_point_id": next_rapid_id,
            "source": rapid_state.get("source"),
            "updated_at": rapid_state.get("updated_at"),
        },
        "basal": {
            "insulin_type": "basal",
            "last_point_id": basal_id,
            "suggested_point_id": next_basal_id,
            "source": basal_state.get("source"),
            "updated_at": basal_state.get("updated_at"),
        },
    }

    return {
        "rapid": rapid_id,
        "basal": basal_id,
        "next_rapid": next_rapid_id,
        "next_basal": next_basal_id,
        "states": resp_states,
        "warnings": warnings or None,
        "source": resp_states.get("rapid", {}).get("source"),  # legacy: keep a simple source key if used elsewhere
    }


@router.get("/state", response_model=InjectionStateResponse)
async def get_injection_state(_: str = Depends(auth_required)):
    """Fetch current global injection state (from DB)."""
    # Assume admin for single user app
    mgr = AsyncInjectionManager("admin")
    payload = await _build_state_payload(mgr)
    return payload


@router.get("/full", response_model=InjectionStateResponse)
async def get_injection_state_full(_: str = Depends(auth_required)):
    """
    Return the full injection state using the same backend storage as /state.
    This is an alias kept for callers expecting /full to mirror /state.
    """
    mgr = AsyncInjectionManager("admin")
    payload = await _build_state_payload(mgr)
    return payload


@router.post("/manual", response_model=InjectionMutationResponse)
async def set_manual_injection(payload: ManualInjectionRequest, _: str = Depends(auth_required)):
    """Persist manual selection of injection point."""
    import logging

    logger = logging.getLogger(__name__)

    mgr = AsyncInjectionManager("admin")
    kind = payload.insulin_type

    try:
        normalized = await mgr.set_current_site(kind, payload.point_id, source="manual")
        logger.info(f"[API /manual] set_current_site returned: {normalized}")
        state = await mgr.get_state()
        saved = state.get(kind, {}).get("last_used_id")

        if saved != normalized:
            logger.critical(f"[API /manual] CRITICAL PERSISTENCE FAILURE. Expected {normalized}, got {saved}")
            raise HTTPException(
                status_code=500,
                detail=f"Persistence mismatch: saved={saved}, expected={normalized}",
            )

        suggested = None
        try:
            suggested_site = await mgr.get_next_site(kind)
            suggested = suggested_site.get("id") if suggested_site else None
        except Exception:
            suggested = None

        resp = {
            "ok": True,
            "insulin_type": payload.insulin_type,
            "point_id": saved,
            "updated_at": state.get(kind, {}).get("updated_at"),
            "source": "manual",
            "suggested_point_id": suggested,
        }
        logger.info(f"[API /manual] Set manual site {kind} -> {saved}; saved_val={saved}")
        return resp
    except ValueError as ve:
        logger.warning(f"[API /manual] Validation failed: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[API /manual] Error persisting manual selection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error saving manual site")


@router.post("/rotate", response_model=InjectionMutationResponse)
async def rotate_injection_site(payload: RotateRequest, _: str = Depends(auth_required)):
    """Frontend notifies backend of an automatic rotation."""
    import logging

    logger = logging.getLogger(__name__)

    logger.info(f"[API /rotate] Received request: type={payload.insulin_type}, target={payload.target}")

    mgr = AsyncInjectionManager("admin")

    kind = payload.insulin_type

    try:
        expected_id = None
        if payload.target:
            # Explicit rotate to target but marked as auto (back-compat)
            logger.info(f"[API /rotate] Setting site via rotate (auto source): {kind} -> {payload.target}")
            expected_id = await mgr.set_current_site(kind, payload.target, source="auto")
            logger.info(f"[API /rotate] set_current_site returned: {expected_id}")
        else:
            # Auto Rotate
            logger.info(f"[API /rotate] Auto rotating: {kind}")
            rotated = await mgr.rotate_site(kind)
            expected_id = rotated.get("id") if rotated else None
            logger.info(f"[API /rotate] rotate_site returned id: {expected_id}")

        # VERIFICATION (Read-After-Write)
        verify_state = await mgr.get_state()
        saved_val = verify_state.get(kind, {}).get("last_used_id")

        logger.info(f"[API /rotate] VERIFY DB: Expected ~ {payload.target if payload.target else expected_id}, Got {saved_val}")
        logger.info(f"[API /rotate] saved_val after verify: {saved_val}")

        if saved_val is None:
            raise HTTPException(status_code=500, detail="DB Write Failed. Missing persisted site")

        if expected_id and saved_val != expected_id:
            logger.error(f"❌ CRITICAL PERSISTENCE FAILURE. DB has {saved_val}, wanted {expected_id}")
            raise HTTPException(
                status_code=500,
                detail=f"DB Write Failed. Got {saved_val}, expected {expected_id}",
            )

        logger.info(f"[API /rotate] Done. Persistence Verified.")

        suggested = None
        try:
            suggested_site = await mgr.get_next_site(kind)
            suggested = suggested_site.get("id") if suggested_site else None
        except Exception:
            suggested = None

        resp = {
            "ok": True,
            "source": "auto",
            "insulin_type": payload.insulin_type,
            "point_id": saved_val,
            "updated_at": verify_state.get(kind, {}).get("updated_at"),
            "suggested_point_id": suggested,
        }
        return resp

    except Exception as e:
        logger.error(f"Error in rotate endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rotate-legacy")
async def rotate_legacy(type: str, target: str, _: str = Depends(auth_required)):
    """Fallback GET endpoint."""
    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"[API /rotate-legacy] GET Request: type={type}, target={target}")

    mgr = AsyncInjectionManager("admin")
    kind = "rapid" if type in ("rapid", "bolus") else "basal"
    await mgr.set_current_site(kind, target, source="manual")
    return {"status": "ok", "method": "GET"}
