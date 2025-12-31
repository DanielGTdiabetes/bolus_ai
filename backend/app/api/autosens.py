from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.db import get_db_session
from app.services.autosens_service import AutosensService
from app.services.settings_service import get_user_settings_service
from app.models.settings import UserSettings
from pydantic import BaseModel

router = APIRouter()

class AutosensResponse(BaseModel):
    ratio: float
    reason: str

@router.get("/calculate", response_model=AutosensResponse, summary="Calculate Autosens Ratio")
async def calculate_autosens_endpoint(
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
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
        result = await AutosensService.calculate_autosens(
            username=current_user.username,
            session=db,
            settings=settings
        )
        
        return AutosensResponse(ratio=result.ratio, reason=result.reason)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Autosens failed: {str(e)}")
