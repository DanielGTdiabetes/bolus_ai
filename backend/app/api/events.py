from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import uuid

from app.core.db import get_db_session
from app.core.security import get_current_user, CurrentUser
from app.models.treatment import Treatment

router = APIRouter()

@router.post("/sick-mode", summary="Toggle Sick Mode and log event")
async def toggle_sick_mode(
    enabled: bool,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Logs a 'Sick Mode Start' or 'Sick Mode End' event in the treatments table.
    This allows historical analysis to exclude these periods.
    """
    event_type = "Note"
    note_text = "Sick Mode Start" if enabled else "Sick Mode End"
    
    # Create a treatment entry acting as a Note/Event
    # We use 'insulin=0, carbs=0' just to use the existing table structure efficiently
    entry = Treatment(
        id=str(uuid.uuid4()),
        user_id=user.username,
        event_type=event_type,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None), # DB uses naive UTC often
        insulin=0.0,
        carbs=0.0,
        notes=note_text,
        entered_by="BolusAI History",
        is_uploaded=False # We might want to upload this to Nightscout as a Note too later
    )
    
    session.add(entry)
    await session.commit()
    
    return {"status": "success", "mode": "enabled" if enabled else "disabled", "event_id": entry.id}
