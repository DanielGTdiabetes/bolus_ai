
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import auth_required
from app.core.db import get_db_session
from app.api.notification_schemas import NotificationSummary, MarkSeenRequest
from app.services.notification_service import get_notification_summary_service, mark_seen_service

router = APIRouter()

@router.get("/summary", response_model=NotificationSummary)
async def get_summary(
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    return await get_notification_summary_service(username, db)

@router.post("/mark-seen")
async def mark_seen(
    payload: MarkSeenRequest,
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    return await mark_seen_service(payload.types, username, db)
