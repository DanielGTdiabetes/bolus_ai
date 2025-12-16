
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.db import get_db_session, _in_memory_store, InMemorySession
from app.models.nightscout_secrets import NightscoutSecrets
from app.core.crypto import encrypt, decrypt
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class NSConfig(BaseModel):
    enabled: bool
    url: str
    api_secret: str
    
async def get_ns_config(session: Optional[AsyncSession], user_id: str) -> Optional[NSConfig]:
    if session:
        result = await session.execute(select(NightscoutSecrets).where(NightscoutSecrets.user_id == user_id))
        record = result.scalar_one_or_none()
        if record:
             try:
                 plain_secret = decrypt(record.api_secret_enc)
                 return NSConfig(
                     enabled=record.enabled,
                     url=record.ns_url,
                     api_secret=plain_secret
                 )
             except Exception as e:
                 logger.error(f"Failed to decrypt Nightscout secret for user {user_id}: {e}")
                 # Fallback? Or raise? Returning None means "not configured" which is safer than crash.
                 return None
    else:
        # In-Memory fallback (if used by tests without mock session)
        # We check _in_memory_store.
        # But `_in_memory_store` structure in `db.py` is rigid. 
        # Let's add support dynamically or skip.
        pass
    
    return None

async def upsert_ns_config(session: Optional[AsyncSession], user_id: str, url: str, api_secret: str, enabled: bool = True):
    # Normalize URL: Force https (unless localhost/http specified explicitly?) request says "validar esquema"
    # Ensure trailing slash
    url = url.strip()
    if not url.endswith("/"):
        url += "/"
    if not (url.lower().startswith("https://") or url.lower().startswith("http://")):
         # Default to https
         url = "https://" + url

    enc_secret = encrypt(api_secret)

    if session:
        # Check existing
        result = await session.execute(select(NightscoutSecrets).where(NightscoutSecrets.user_id == user_id))
        record = result.scalar_one_or_none()
        
        if record:
            record.ns_url = url
            record.api_secret_enc = enc_secret
            record.enabled = enabled
            record.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            record = NightscoutSecrets(
                user_id=user_id,
                ns_url=url,
                api_secret_enc=enc_secret,
                enabled=enabled,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
            )
            session.add(record)
        
        await session.commit()
    else:
        logger.warning("No DB session for upsert_ns_config")

async def delete_ns_config(session: Optional[AsyncSession], user_id: str):
    if session:
        result = await session.execute(select(NightscoutSecrets).where(NightscoutSecrets.user_id == user_id))
        record = result.scalar_one_or_none()
        if record:
            await session.delete(record)
            await session.commit()
