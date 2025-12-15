from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import auth_required
from app.core.db import get_db_session
from app.api.notification_schemas import NotificationSummary, MarkSeenRequest, PushSubscription
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

@router.post("/subscribe")
async def subscribe_push(
    sub: PushSubscription,
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    # Store subscription in DB or JSON (Placeholder)
    # In a real app, save to 'user_push_subscriptions' table
    print(f"New Push Subscription for {username}: {sub.endpoint[:20]}...")
    return {"ok": True, "message": "Subscribed"}
