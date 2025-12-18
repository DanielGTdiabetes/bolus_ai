import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.security import CurrentUser, get_current_user
from app.core.settings import Settings, get_settings
from app.core.config import get_google_api_key
from app.services.restaurant import (
    RestaurantMenuResult,
    RestaurantPlateEstimate,
    RestaurantPlateResult,
    analyze_menu_with_gemini,
    analyze_plate_with_gemini,
    compare_plate_with_gemini,
    guardrails_from_totals,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _validate_image(image: UploadFile, settings: Settings):
    max_bytes = settings.vision.max_image_mb * 1024 * 1024
    if image.size and image.size > max_bytes:
        raise HTTPException(status_code=413, detail=f"Image too large (> {settings.vision.max_image_mb}MB)")
    if image.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(status_code=415, detail="Unsupported image type")


def _ensure_gemini_enabled(settings: Settings):
    if not get_google_api_key():
        raise HTTPException(status_code=501, detail="missing_google_api_key: Gemini API Key not configured")


@router.post("/analyze_menu", response_model=RestaurantMenuResult, summary="Analyze restaurant menu")
async def analyze_menu(
    image: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    _ensure_gemini_enabled(settings)
    _validate_image(image, settings)

    content = await image.read()
    size_mb = len(content) / (1024 * 1024)
    logger.info("Restaurant analyze_menu user=%s size=%.2fMB", current_user.username, size_mb)

    try:
        return await analyze_menu_with_gemini(content, image.content_type)
    except RuntimeError as exc:
        logger.error("Restaurant analyze error: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected error in analyze_menu")
        raise HTTPException(status_code=500, detail="Internal error during menu analysis") from exc


@router.post("/analyze_menu_text", response_model=RestaurantMenuResult, summary="Analyze restaurant menu from text")
async def analyze_menu_text(
    description: str = Form(...),
    current_user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    _ensure_gemini_enabled(settings)
    logger.info("Restaurant analyze_menu_text user=%s length=%d", current_user.username, len(description))

    # Lazy import to avoid circular dep if any (standard pattern matches other endpoints)
    from app.services.restaurant import analyze_menu_text_with_gemini
    
    try:
        return await analyze_menu_text_with_gemini(description)
    except RuntimeError as exc:
        logger.error("Restaurant analyze text error: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc: 
        logger.exception("Unexpected error in analyze_menu_text")
        raise HTTPException(status_code=500, detail="Internal error during text menu analysis") from exc


@router.post("/analyze_plate", response_model=RestaurantPlateEstimate, summary="Analyze individual plate")
async def analyze_plate(
    image: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    _ensure_gemini_enabled(settings)
    _validate_image(image, settings)

    content = await image.read()
    size_mb = len(content) / (1024 * 1024)
    logger.info("Restaurant analyze_plate user=%s size=%.2fMB", current_user.username, size_mb)

    try:
        return await analyze_plate_with_gemini(content, image.content_type)
    except RuntimeError as exc:
        logger.error("Restaurant plate analyze error: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected error in analyze_plate")
        raise HTTPException(status_code=500, detail="Internal error during plate analysis") from exc


@router.post("/compare_plate", response_model=RestaurantPlateResult, summary="Compare served plate vs expected")
async def compare_plate(
    image: UploadFile | None = File(None),
    expected_carbs: float = Form(..., alias="expectedCarbs"),
    actual_carbs: float | None = Form(None, alias="actualCarbs"),
    confidence: float | None = Form(None),
    current_user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if image is None and actual_carbs is None:
        raise HTTPException(status_code=400, detail="image_or_actual_required")

    if image is None and actual_carbs is not None:
        logger.info(
            "Restaurant guardrails-only user=%s expected=%.1f actual=%.1f", current_user.username, expected_carbs, actual_carbs
        )
        try:
            return guardrails_from_totals(
                expected_carbs,
                actual_carbs,
                confidence,
                base_warnings=["Estimación agregada"],
                reasoning_short="Ajuste total de sesión",
            )
        except RuntimeError as exc:
            logger.error("Restaurant guardrail error: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    _ensure_gemini_enabled(settings)
    _validate_image(image, settings)
    content = await image.read()
    size_mb = len(content) / (1024 * 1024)
    logger.info(
        "Restaurant compare_plate user=%s size=%.2fMB expected=%.1f",
        current_user.username,
        size_mb,
        expected_carbs,
    )

    try:
        return await compare_plate_with_gemini(content, image.content_type, expected_carbs, confidence_override=confidence)
    except RuntimeError as exc:
        logger.error("Restaurant compare error: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected error in compare_plate")
        raise HTTPException(status_code=500, detail="Internal error during plate comparison") from exc

# --- Persistence Endpoints ---

from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.services.restaurant_db import RestaurantDBService

class CreateSessionRequest(BaseModel):
    expectedCarbs: float
    expectedFat: Optional[float] = 0.0
    expectedProtein: Optional[float] = 0.0
    items: List[Dict[str, Any]] = []
    notes: str = ""

class AddPlateRequest(BaseModel):
    carbs: float
    fat: float
    protein: float
    confidence: Optional[float] = None
    warnings: List[str] = []
    reasoning_short: str = ""
    name: Optional[str] = None

class FinalizeSessionRequest(BaseModel):
    outcomeScore: Optional[int] = None

@router.post("/session/start", summary="Start a new persistent restaurant session")
async def start_session(
    data: CreateSessionRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        # Pydantic v2 usually returns str for UUID if coerced, but let's be safe
        uid = str(current_user.id) if hasattr(current_user, 'id') else current_user.username
        
        session = await RestaurantDBService.create_session(
            user_id=uid,
            expected_carbs=data.expectedCarbs,
            expected_fat=data.expectedFat or 0.0,
            expected_protein=data.expectedProtein or 0.0,
            items=data.items,
            notes=data.notes
        )
        if not session:
            # Fallback if DB not configured
            return {"status": "ok", "mode": "memory", "warning": "Persistence not available"}
        return {"status": "ok", "mode": "db", "sessionId": str(session.id)}
    except Exception as e:
        logger.error(f"Error starting session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/session/{session_id}/plate", summary="Add plate to session")
async def add_plate_to_session(
    session_id: str,
    data: AddPlateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        updated = await RestaurantDBService.add_plate(
            session_id=session_id,
            plate_data=data.model_dump()
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "ok", "actualCarbs": updated.actual_carbs}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding plate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/session/{session_id}/finalize", summary="Finalize session")
async def finalize_session(
    session_id: str,
    data: FinalizeSessionRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        updated = await RestaurantDBService.finalize_session(
            session_id=session_id,
            outcome_score=data.outcomeScore
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "ok", "delta": updated.delta_carbs}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error finalizing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
