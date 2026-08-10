from __future__ import annotations

from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.security import CurrentUser, get_current_user
from app.services.meal_session_service import (
    finish_meal_session,
    get_active_meal_session,
    get_meal_session,
    record_carbs_added,
    start_meal_session,
    summarize_meal_session,
)

router = APIRouter()


class StartMealSessionRequest(BaseModel):
    meal_slot: Optional[Literal["breakfast", "lunch", "dinner", "snack"]] = None
    label: Optional[str] = Field(default=None, max_length=160)
    source: str = Field(default="app", min_length=1, max_length=64)


class AddMealCarbsRequest(BaseModel):
    client_event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=8, max_length=128)
    carbs_g: float = Field(ge=0, le=500)
    fat_g: float = Field(default=0, ge=0, le=500)
    protein_g: float = Field(default=0, ge=0, le=500)
    fiber_g: float = Field(default=0, ge=0, le=500)
    label: Optional[str] = Field(default=None, max_length=200)
    source: Optional[str] = Field(default=None, max_length=64)


@router.post("/start", summary="Start or resume the current meal session")
async def start_session(
    payload: StartMealSessionRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    existing = await get_active_meal_session(db, user.username)
    row = existing or await start_meal_session(
        db,
        user_id=user.username,
        meal_slot=payload.meal_slot,
        label=payload.label,
        source=payload.source,
    )
    return {"resumed": existing is not None, "session": summarize_meal_session(row)}


@router.get("/active", summary="Get the current active meal session")
async def active_session(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    row = await get_active_meal_session(db, user.username)
    return {"session": summarize_meal_session(row) if row else None}


@router.get("/{session_id}", summary="Get one meal session")
async def read_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    row = await get_meal_session(db, user_id=user.username, session_id=session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Meal session not found")
    return summarize_meal_session(row)


@router.post("/{session_id}/carbs", summary="Record newly added carbohydrates in a meal session")
async def add_carbs(
    session_id: str,
    payload: AddMealCarbsRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        await record_carbs_added(
            db,
            user_id=user.username,
            session_id=session_id,
            client_event_id=payload.client_event_id,
            carbs_g=payload.carbs_g,
            fat_g=payload.fat_g,
            protein_g=payload.protein_g,
            fiber_g=payload.fiber_g,
            payload={"label": payload.label, "source": payload.source},
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Meal session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Meal session is not active") from exc

    row = await get_meal_session(db, user_id=user.username, session_id=session_id)
    return summarize_meal_session(row)


@router.post("/{session_id}/close", summary="Close a meal session")
async def close_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        row = await finish_meal_session(
            db,
            user_id=user.username,
            session_id=session_id,
            status="closed",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Meal session not found") from exc
    return summarize_meal_session(row)


@router.post("/{session_id}/cancel", summary="Cancel a meal session")
async def cancel_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        row = await finish_meal_session(
            db,
            user_id=user.username,
            session_id=session_id,
            status="cancelled",
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Meal session not found") from exc
    return summarize_meal_session(row)
