
from datetime import datetime
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import auth_required
from app.core.db import get_db_session
from app.models.settings import UserSettings
from app.services import settings_service

router = APIRouter()

# --- Schemas ---

class SettingsResponse(BaseModel):
    settings: Optional[dict]
    version: int
    updated_at: Optional[datetime]

class UpdateRequest(BaseModel):
    settings: dict
    version: int

class ConflictResponse(BaseModel):
    detail: str
    server_version: int
    server_settings: Optional[dict]

class ImportRequest(BaseModel):
    settings: dict

class ImportResponse(SettingsResponse):
    imported: bool

# --- Endpoints ---

@router.get("/", response_model=SettingsResponse)
async def get_settings(
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    return await settings_service.get_user_settings_service(username, db)

@router.put("/", response_model=SettingsResponse, responses={409: {"model": ConflictResponse}})
async def update_settings(
    payload: UpdateRequest,
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        # Pydantic dump for storage
        settings_dict = payload.settings
        return await settings_service.update_user_settings_service(
            username, 
            settings_dict, 
            payload.version, 
            db
        )
    except settings_service.VersionConflictError as e:
        return  JSONResponse(
            status_code=409,
            content=ConflictResponse(
                detail="Version conflict",
                server_version=e.server_version,
                server_settings=e.server_settings
            ).model_dump(mode='json')
        )

@router.get("/ml-status")
async def get_ml_status(
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    # Count training data points
    from sqlalchemy import text
    try:
        # Simple count query
        result = await db.execute(text("SELECT COUNT(*) FROM ml_training_data WHERE username = :u"), {"u": username})
        count = result.scalar() or 0
    except Exception:
        count = 0
    
    # Target: 5000 points (approx 17 days of continuous 5-min data) for initial training
    target_points = 5000
    
    # Calculate progress
    percent = min(100, int((count / target_points) * 100))
    
    # Hardcoded status check for now, later linked to real model state
    # If ML service deployment was automated, we'd check that too
    
    return {
        "status": "learning" if percent < 100 else "ready",
        "data_points": count,
        "percent_complete": percent,
        "target_points": target_points,
        "days_collected": round(count * 5 / 60 / 24, 1), # 5 min interval
        "accuracy": None, # Placeholder: Will be calculated from validation set
        "mae": None # Placeholder: Mean Absolute Error
    }

@router.post("/import", response_model=ImportResponse)
async def import_settings(
    payload: ImportRequest,
    username: str = Depends(auth_required),
    db: AsyncSession = Depends(get_db_session)
):
    settings_dict = payload.settings
    return await settings_service.import_user_settings_service(
        username,
        settings_dict,
        db
    )

# Legacy imports for JSONResponse
from fastapi.responses import JSONResponse
