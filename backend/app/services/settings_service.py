
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.settings import UserSettingsDB, UserSettings
from app.utils.timezone import set_user_timezone

logger = logging.getLogger(__name__)


def _sync_timezone_cache(user_id: str, settings_dict: dict) -> None:
    """Update the timezone module cache when user settings change."""
    tz = None
    if isinstance(settings_dict, dict):
        tz = settings_dict.get("timezone")
    if tz:
        set_user_timezone(tz, user_id)

async def get_user_settings_service(user_id: str, db: AsyncSession):
    stmt = select(UserSettingsDB).where(UserSettingsDB.user_id == user_id)
    row = (await db.execute(stmt)).scalars().first()
    
    if not row:
        return {
            "settings": None,
            "version": 0,
            "updated_at": None
        }

    _sync_timezone_cache(user_id, row.settings)
    return {
        "settings": row.settings,
        "version": row.version,
        "updated_at": row.updated_at
    }

class VersionConflictError(Exception):
    def __init__(self, server_version, server_settings):
        self.server_version = server_version
        self.server_settings = server_settings

async def update_user_settings_service(user_id: str, new_settings: dict, client_version: int, db: AsyncSession):
    # Fetch current
    stmt = select(UserSettingsDB).where(UserSettingsDB.user_id == user_id)
    row = (await db.execute(stmt)).scalars().first()
    
    if not row:
        # Implicit create if missing? 
        # Requirement says "Si version no coincide ... 409".
        # If row missing, server version is effectively 0.
        # If client_version is 0 (first save), allow create?
        # Requirement Put: "Si version no coincide con la actual en DB -> 409".
        # If DB missing, version is 0. If client sends 0 -> match -> Create.
        
        current_ver = 0
        if client_version != current_ver:
             raise VersionConflictError(0, None)
             
        # Create
        new_row = UserSettingsDB(
            user_id=user_id,
            settings=new_settings,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(new_row)
        await db.commit()
        return {"settings": new_settings, "version": 1, "updated_at": new_row.updated_at}
        
    else:
        # Row exists Check version
        if row.version != client_version:
            raise VersionConflictError(row.version, row.settings)
            
        # Match. Update.
        row.settings = new_settings
        row.version = row.version + 1
        row.updated_at = datetime.now(timezone.utc)

        await db.commit()
        _sync_timezone_cache(user_id, new_settings)
        return {"settings": row.settings, "version": row.version, "updated_at": row.updated_at}

async def import_user_settings_service(user_id: str, settings: dict, db: AsyncSession):
    stmt = select(UserSettingsDB).where(UserSettingsDB.user_id == user_id)
    row = (await db.execute(stmt)).scalars().first()
    
    if row:
        # Already exists. Do NOT overwrite. Return server state.
        return {
            "imported": False,
            "settings": row.settings,
            "version": row.version,
            "updated_at": row.updated_at
        }
    else:
        # Create
        new_row = UserSettingsDB(
            user_id=user_id,
            settings=settings,
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(new_row)
        await db.commit()
        
        return {
            "imported": True,
            "settings": settings,
            "version": 1,
            "updated_at": new_row.updated_at
        }
