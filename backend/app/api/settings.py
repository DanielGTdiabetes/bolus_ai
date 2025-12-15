
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
