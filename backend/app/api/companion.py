from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.security import CurrentUser, get_current_user
from app.services.companion_service import (
    act_on_episode,
    evaluate_companion_state,
    get_or_create_preferences,
    list_active_episodes,
    serialize_episode,
    serialize_preferences,
    update_preferences,
)

router = APIRouter()


class EpisodeActionRequest(BaseModel):
    action: Literal["acknowledge", "snooze", "dismiss", "resolve"]
    snooze_minutes: int = Field(default=30, ge=10, le=720)


class CompanionPreferencePatch(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[Literal["quiet", "balanced", "active"]] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    repeat_critical_minutes: Optional[int] = Field(default=None, ge=10, le=180)
    repeat_high_minutes: Optional[int] = Field(default=None, ge=30, le=1440)

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def validate_time(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        parts = value.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("Usa el formato HH:MM")
        hour, minute = map(int, parts)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("Hora no válida")
        return f"{hour:02d}:{minute:02d}"


@router.get("/snapshot")
async def get_snapshot(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    return await evaluate_companion_state(current_user.username, db)


@router.get("/episodes")
async def get_active_episodes(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    rows = await list_active_episodes(current_user.username, db)
    return {"episodes": [serialize_episode(row) for row in rows]}


@router.post("/episodes/{episode_id}/action")
async def episode_action(
    episode_id: UUID,
    payload: EpisodeActionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        row = await act_on_episode(
            current_user.username, episode_id, payload.action, db,
            snooze_minutes=payload.snooze_minutes,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Episodio no encontrado")
    return {"ok": True, "id": str(row.id), "status": row.status}


@router.get("/preferences")
async def get_preferences(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    pref = await get_or_create_preferences(current_user.username, db)
    await db.commit()
    return serialize_preferences(pref)


@router.patch("/preferences")
async def patch_preferences(
    payload: CompanionPreferencePatch,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    pref = await update_preferences(
        current_user.username, payload.model_dump(exclude_none=True), db
    )
    return serialize_preferences(pref)
