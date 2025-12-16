
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.db import get_db_session
from app.core.settings import get_settings, Settings
from app.services.store import DataStore
from app.models.settings import UserSettings
from app.services.nightscout_client import NightscoutClient
from app.services.pattern_analysis import run_analysis_service, get_summary_service

router = APIRouter()

def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))

@router.post("/bolus/run", summary="Run post-bolus pattern analysis")
async def run_analysis_endpoint(
    payload: dict = Body(...),
    current_user: Any = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
    db: AsyncSession = Depends(get_db_session)
):
    days = payload.get("days", 30)
    
    settings = store.load_settings()
    ns_config = settings.nightscout
    
    # Relaxed NS check: If not configured, we just don't pass a client
    client = None
    if ns_config.enabled and ns_config.url:
        client = NightscoutClient(base_url=ns_config.url, token=ns_config.token)
    
    try:
        user_id = current_user.username
        
        result = await run_analysis_service(
            user_id=user_id,
            days=days,
            settings=settings,
            ns_client=client,
            db=db
        )
        if "error" in result:
             raise HTTPException(status_code=502, detail=result["error"])
        return result
    finally:
        await client.aclose()

@router.get("/bolus/summary", summary="Get post-bolus analysis summary")
async def get_summary_endpoint(
    days: int = 30,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    user_id = current_user.username
    return await get_summary_service(user_id=user_id, days=days, db=db)
