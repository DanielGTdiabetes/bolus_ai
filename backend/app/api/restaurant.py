import logging
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.core.security import CurrentUser, get_current_user
from app.core.settings import Settings, get_settings
from app.core.config import get_google_api_key
from app.services.restaurant import (
    RestaurantPlateEstimate,
    RestaurantMenuResult,
    RestaurantPlateResult,
    analyze_plate_with_gemini,
    analyze_menu_with_gemini,
    analyze_menu_text_with_gemini,
    guardrails_from_totals,
)
from app.core.db import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.settings_service import get_user_settings_service
from app.models.settings import UserSettings
from app.models.restaurant_session import RestaurantSessionV2

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

def _attach_request_id(request: Request, response: Response) -> str:
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    response.headers["X-Request-Id"] = request_id
    return request_id


async def _resolve_settings(base_settings: Settings, user: CurrentUser, session: AsyncSession) -> Settings:
    try:
        data = await get_user_settings_service(user.username, session)
        if data and data.get("settings"):
            user_conf = UserSettings.migrate(data["settings"])
            if user_conf.vision.provider:
                base_settings = base_settings.model_copy(deep=True)
                base_settings.vision.provider = user_conf.vision.provider
                if user_conf.vision.gemini_key:
                    base_settings.vision.google_api_key = user_conf.vision.gemini_key
                if user_conf.vision.gemini_model:
                    base_settings.vision.gemini_model = user_conf.vision.gemini_model
                if user_conf.vision.openai_key:
                    base_settings.vision.openai_api_key = user_conf.vision.openai_key
                if user_conf.vision.openai_model:
                    base_settings.vision.openai_model = user_conf.vision.openai_model
    except Exception as e:
        logger.warning(f"Failed to resolve user vision settings: {e}")
    return base_settings


async def _get_user_isf(user: CurrentUser, session: AsyncSession) -> float | None:
    """Obtener ISF del usuario para el momento actual"""
    try:
        data = await get_user_settings_service(user.username, session)
        if data and data.get("settings"):
            user_conf = UserSettings.migrate(data["settings"])
            return user_conf.bolus.isf
    except Exception as e:
        logger.warning(f"Failed to get user ISF: {e}")
    return None


class MenuTextRequest(BaseModel):
    description: str


class ComparePlateRequest(BaseModel):
    expectedCarbs: float
    actualCarbs: float
    confidence: float | None = None


class SessionStartRequest(BaseModel):
    expectedCarbs: float
    expectedFat: Optional[float] = None
    expectedProtein: Optional[float] = None
    items: Optional[List[Any]] = None
    warnings: Optional[List[str]] = None


class SessionPlateRequest(BaseModel):
    carbs: float
    fat: Optional[float] = None
    protein: Optional[float] = None
    confidence: Optional[float] = None
    warnings: Optional[List[str]] = None
    reasoning_short: Optional[str] = None
    name: Optional[str] = None


class SessionFinalizeRequest(BaseModel):
    outcomeScore: Optional[int] = None


@router.post("/analyze_menu", response_model=RestaurantMenuResult, summary="Analyze restaurant menu from image")
async def analyze_menu(
    request: Request,
    response: Response,
    image: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    base_settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db_session),
):
    """Analizar foto de carta/menú para estimar HC totales"""
    request_id = _attach_request_id(request, response)
    settings = await _resolve_settings(base_settings, current_user, session)
    _ensure_gemini_enabled(settings)
    _validate_image(image, settings)

    content = await image.read()
    size_mb = len(content) / (1024 * 1024)
    logger.info("Restaurant analyze_menu user=%s request_id=%s size=%.2fMB", current_user.username, request_id, size_mb)

    try:
        return await analyze_menu_with_gemini(content, image.content_type)
    except RuntimeError as exc:
        logger.error("Restaurant menu analyze error: request_id=%s error=%s", request_id, exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error in analyze_menu request_id=%s", request_id)
        raise HTTPException(status_code=500, detail="Internal error during menu analysis") from exc


@router.post("/analyze_menu_text", response_model=RestaurantMenuResult, summary="Analyze menu from text description")
async def analyze_menu_text(
    request: Request,
    response: Response,
    payload: MenuTextRequest,
    current_user: CurrentUser = Depends(get_current_user),
    base_settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db_session),
):
    """Analizar descripción de texto de menú para estimar HC totales"""
    request_id = _attach_request_id(request, response)
    logger.info("Restaurant analyze_menu_text user=%s request_id=%s", current_user.username, request_id)

    try:
        return await analyze_menu_text_with_gemini(payload.description)
    except RuntimeError as exc:
        logger.error("Restaurant menu text analyze error: request_id=%s error=%s", request_id, exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error in analyze_menu_text request_id=%s", request_id)
        raise HTTPException(status_code=500, detail="Internal error during menu text analysis") from exc


@router.post("/compare_plate", response_model=RestaurantPlateResult, summary="Calculate adjustment from expected vs actual")
async def compare_plate(
    request: Request,
    response: Response,
    payload: ComparePlateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Calcular ajuste seguro comparando HC esperados vs reales"""
    request_id = _attach_request_id(request, response)
    logger.info("Restaurant compare_plate user=%s request_id=%s expected=%s actual=%s", 
                current_user.username, request_id, payload.expectedCarbs, payload.actualCarbs)

    user_isf = await _get_user_isf(current_user, session)
    
    try:
        result = guardrails_from_totals(
            expected_carbs=payload.expectedCarbs,
            actual_carbs=payload.actualCarbs,
            confidence=payload.confidence,
            user_isf=user_isf,
        )
        return result
    except RuntimeError as exc:
        logger.error("Restaurant compare_plate error: request_id=%s error=%s", request_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error in compare_plate request_id=%s", request_id)
        raise HTTPException(status_code=500, detail="Internal error during plate comparison") from exc


@router.post("/analyze_plate", response_model=RestaurantPlateEstimate, summary="Analyze individual plate")
async def analyze_plate(
    request: Request,
    response: Response,
    image: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    base_settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_db_session),
):
    request_id = _attach_request_id(request, response)
    settings = await _resolve_settings(base_settings, current_user, session)
    _ensure_gemini_enabled(settings)
    _validate_image(image, settings)

    content = await image.read()
    size_mb = len(content) / (1024 * 1024)
    logger.info(
        "Restaurant analyze_plate user=%s request_id=%s size=%.2fMB",
        current_user.username,
        request_id,
        size_mb,
    )

    try:
        return await analyze_plate_with_gemini(content, image.content_type)
    except RuntimeError as exc:
        logger.error("Restaurant plate analyze error: request_id=%s error=%s", request_id, exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error in analyze_plate request_id=%s", request_id)
        raise HTTPException(status_code=500, detail="Internal error during plate analysis") from exc


# --- Session Persistence Endpoints ---

@router.post("/session/start", summary="Start a restaurant session")
async def start_session(
    payload: SessionStartRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    row = RestaurantSessionV2(
        user_id=current_user.username,
        expected_carbs=payload.expectedCarbs,
        expected_fat=payload.expectedFat,
        expected_protein=payload.expectedProtein,
        items_json=payload.items or [],
        warnings_json=payload.warnings or [],
        plates_json=[],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info("Restaurant session started user=%s session_id=%s", current_user.username, row.id)
    return {"sessionId": str(row.id)}


@router.post("/session/{session_id}/plate", summary="Add a plate to a restaurant session")
async def add_plate(
    session_id: str,
    payload: SessionPlateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(RestaurantSessionV2).where(
            RestaurantSessionV2.id == uuid.UUID(session_id),
            RestaurantSessionV2.user_id == current_user.username,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    plates = list(row.plates_json or [])
    plates.append(payload.model_dump(exclude_none=True))
    row.plates_json = plates
    row.actual_carbs = sum(p.get("carbs", 0) for p in plates)
    row.actual_fat = sum(p.get("fat", 0) for p in plates)
    row.actual_protein = sum(p.get("protein", 0) for p in plates)
    row.delta_carbs = row.actual_carbs - (row.expected_carbs or 0)
    await session.commit()
    return {"ok": True, "plateCount": len(plates)}


@router.post("/session/{session_id}/finalize", summary="Finalize a restaurant session")
async def finalize_session(
    session_id: str,
    payload: SessionFinalizeRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(RestaurantSessionV2).where(
            RestaurantSessionV2.id == uuid.UUID(session_id),
            RestaurantSessionV2.user_id == current_user.username,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    row.finalized_at = datetime.now(timezone.utc)
    if payload.outcomeScore is not None:
        row.outcome_score = payload.outcomeScore
    await session.commit()
    logger.info("Restaurant session finalized user=%s session_id=%s", current_user.username, session_id)
    return {"ok": True}

