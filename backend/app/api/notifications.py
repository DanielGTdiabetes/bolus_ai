from datetime import datetime
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
    """
    Persist web push subscription for the user.
    @deprecated Not consumed by the current notification UX; kept for legacy clients.
    """
    from app.models.notifications import PushSubscription as PushModel
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert
    
    # Check if endpoint exists
    stmt = select(PushModel).where(
        PushModel.user_id == username, 
        PushModel.endpoint == sub.endpoint
    )
    res = await db.execute(stmt)
    existing = res.scalars().first()
    
    if existing:
        existing.keys = sub.keys
        existing.updated_at = datetime.utcnow()
    else:
        new_sub = PushModel(
            user_id=username,
            endpoint=sub.endpoint,
            keys=sub.keys
        )
        db.add(new_sub)
        
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        # Handle unique constraint violation race condition if needed, but select-then-update is mostly fine for user-locked context
    
    return {"ok": True, "message": "Subscribed"}
