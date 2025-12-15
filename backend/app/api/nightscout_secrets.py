
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, CurrentUser
from app.core.db import get_db_session
from app.services.nightscout_secrets_service import get_ns_config, upsert_ns_config, delete_ns_config

router = APIRouter()

class SecretResponse(BaseModel):
    enabled: bool
    url: Optional[str]
    has_secret: bool

class SecretPayload(BaseModel):
    url: str
    api_secret: str
    enabled: bool = True

@router.get("/secret", response_model=SecretResponse, summary="Check status of stored secret")
async def get_secret_status(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    config = await get_ns_config(session, user.username)
    if config:
        return SecretResponse(
            enabled=config.enabled,
            url=config.url,
            has_secret=True # Never return the actual secret
        )
    return SecretResponse(enabled=False, url=None, has_secret=False)

@router.put("/secret", summary="Store Nightscout Credentials securely")
async def put_secret(
    payload: SecretPayload,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    if not payload.url or not payload.api_secret:
        raise HTTPException(status_code=400, detail="URL and API Secret are required")
        
    await upsert_ns_config(session, user.username, payload.url, payload.api_secret, payload.enabled)
    return {"success": True}

@router.delete("/secret", summary="Remove stored credentials")
async def delete_secret(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    await delete_ns_config(session, user.username)
    return {"success": True}
