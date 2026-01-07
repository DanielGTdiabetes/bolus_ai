from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import get_current_user
from app.core.db import get_db_session
from app.core.settings import Settings, get_settings
from app.services.autosens_service import AutosensService
from app.services.smart_filter import FilterConfig
from app.services.settings_service import get_user_settings_service
from app.models.settings import UserSettings
from app.models.autosens import AutosensRun
from pydantic import BaseModel

router = APIRouter()

class AutosensResponse(BaseModel):
    ratio: float
    reason: str


class AutosensRunResponse(BaseModel):
    id: int
    created_at_utc: Optional[str]
    ratio: float
    window_hours: int
    input_summary_json: dict
    clamp_applied: bool
    reason_flags: list[str]
    enabled_state: bool

@router.get("/calculate", response_model=AutosensResponse, summary="Calculate Autosens Ratio")
async def calculate_autosens_endpoint(
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    try:
        # Load Settings
        data = await get_user_settings_service(current_user.username, db)
        settings = None
        if data and data.get("settings"):
            settings = UserSettings.migrate(data["settings"])
        else:
             # Fallback? AutosensService requires settings.
             raise HTTPException(status_code=400, detail="Settings not found for user")

        # Run Service
        compression_config = FilterConfig(
            enabled=settings.nightscout.filter_compression,
            night_start_hour=settings.nightscout.filter_night_start,
            night_end_hour=settings.nightscout.filter_night_end,
            drop_threshold_mgdl=settings.nightscout.filter_drop_mgdl,
            rebound_threshold_mgdl=settings.nightscout.filter_rebound_mgdl,
            rebound_window_minutes=settings.nightscout.filter_window_min
        )
        result = await AutosensService.calculate_autosens(
            username=current_user.username,
            session=db,
            settings=settings,
            record_run=True,
            compression_config=compression_config,
        )
        
        return AutosensResponse(ratio=result.ratio, reason=result.reason)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Autosens failed: {str(e)}")


@router.get("/runs", response_model=list[AutosensRunResponse], summary="List Autosens Runs")
async def list_autosens_runs(
    limit: int = Query(50, ge=1, le=200),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    stmt = (
        select(AutosensRun)
        .where(AutosensRun.user_id == current_user.username)
        .order_by(AutosensRun.created_at_utc.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        AutosensRunResponse(
            id=row.id,
            created_at_utc=row.created_at_utc.isoformat() if row.created_at_utc else None,
            ratio=row.ratio,
            window_hours=row.window_hours,
            input_summary_json=row.input_summary_json,
            clamp_applied=row.clamp_applied,
            reason_flags=row.reason_flags or [],
            enabled_state=row.enabled_state,
        )
        for row in rows
    ]
