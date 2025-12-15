
import pytest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from app.services.settings_service import get_user_settings_service, update_user_settings_service, import_user_settings_service, VersionConflictError
from app.models.settings import UserSettingsDB

@pytest.mark.asyncio
async def test_get_settings_empty():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    # Mock empty result
    mr = MagicMock()
    mr.scalars.return_value.first.return_value = None
    db.execute.return_value = mr
    
    res = await get_user_settings_service(user_id, db)
    assert res["settings"] is None
    assert res["version"] == 0

@pytest.mark.asyncio
async def test_import_settings():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    # Mock Check: Empty
    mr = MagicMock()
    mr.scalars.return_value.first.return_value = None
    db.execute.return_value = mr
    
    data = {"foo": "bar"}
    res = await import_user_settings_service(user_id, data, db)
    
    assert res["imported"] is True
    assert res["version"] == 1
    assert db.add.called
    assert db.commit.called

@pytest.mark.asyncio
async def test_update_settings_success():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    # Mock existing
    existing = UserSettingsDB(
        user_id=user_id,
        settings={"old": 1},
        version=5,
        updated_at=datetime.utcnow()
    )
    mr = MagicMock()
    mr.scalars.return_value.first.return_value = existing
    db.execute.return_value = mr
    
    new_data = {"new": 2}
    res = await update_user_settings_service(user_id, new_data, 5, db)
    
    assert res["version"] == 6
    assert existing.settings == new_data
    assert existing.version == 6
    assert db.commit.called

@pytest.mark.asyncio
async def test_update_settings_conflict():
    user_id = str(uuid.uuid4())
    db = AsyncMock()
    
    # Mock existing version 10
    existing = UserSettingsDB(
        user_id=user_id,
        settings={"val": 10},
        version=10
    )
    mr = MagicMock()
    mr.scalars.return_value.first.return_value = existing
    db.execute.return_value = mr
    
    # Client sends version 9 (stale)
    with pytest.raises(VersionConflictError) as exc:
        await update_user_settings_service(user_id, {"val": 11}, 9, db)
        
    assert exc.value.server_version == 10
    assert exc.value.server_settings["val"] == 10
