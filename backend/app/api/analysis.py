
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
    from app.services.settings_service import get_user_settings_service
    
    # Helper to load settings from DB with fallback
    async def _load_settings() -> UserSettings:
        # DB first
        data = await get_user_settings_service(current_user.username, db)
        s_obj = None
        if data and data.get("settings"):
            s_obj = UserSettings.migrate(data["settings"])
            # Inject updated_at for analysis optimization
            dt = data.get("updated_at")
            if dt:
                 s_obj.updated_at = dt
        
        if not s_obj:
            # Fallback to file Store
            s_obj = store.load_settings()
        return s_obj

    days = payload.get("days", 30)
    
    settings = await _load_settings()

    # Resolve Nightscout Credentials (DB Priority)
    from app.services.nightscout_secrets_service import get_ns_config
    
    db_ns_config = await get_ns_config(db, current_user.username)
    
    final_url = None
    final_token = None
    
    if db_ns_config and db_ns_config.enabled and db_ns_config.url:
        final_url = db_ns_config.url
        final_token = db_ns_config.api_secret
    else:
        # Fallback to local settings in store? Actually no, local file store is being deprecated in favor of DB.
        # But let's check store['nightscout'] just in case for legacy transition
        legacy_ns = settings.get("nightscout")
        if legacy_ns and legacy_ns.get("url"):
             final_url = legacy_ns.get("url")
             final_token = legacy_ns.get("token")
        
    client = None
    if final_url:
        client = NightscoutClient(base_url=final_url, token=final_token)
    elif not final_url:
         # If truly no config found anywhere, warn but proceed with DB-only analysis
         pass
    
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
        if client:
            await client.aclose()

@router.get("/bolus/summary", summary="Get post-bolus analysis summary")
async def get_summary_endpoint(
    days: int = 30,
    current_user: Any = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
    db: AsyncSession = Depends(get_db_session)
):
    from app.services.settings_service import get_user_settings_service
    
    # Helper (duplicated locally for now or we could move it, but this is simple enough)
    async def _load_settings_summary() -> UserSettings:
        data = await get_user_settings_service(current_user.username, db)
        s_obj = None
        if data and data.get("settings"):
            s_obj = UserSettings.migrate(data["settings"])
            dt = data.get("updated_at")
            if dt:
                 s_obj.updated_at = dt
        if not s_obj:
            s_obj = store.load_settings()
        return s_obj

    user_id = current_user.username
    settings = await _load_settings_summary()
    return await get_summary_service(user_id=user_id, days=days, db=db, settings=settings)


@router.get("/shadow/logs", summary="Get Shadow Mode logs")
async def get_shadow_logs(
    limit: int = 50,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    from app.models.learning import ShadowLog
    from sqlalchemy import select
    
    stmt = (
        select(ShadowLog)
        .where(ShadowLog.user_id == current_user.username)
        .order_by(ShadowLog.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return logs
