from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datastore import UserStore
from app.core.security import CurrentUser
from app.core.settings import get_settings
from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2
from app.services.bolus_calc_service import calculate_bolus_stateless_service
from app.services.store import DataStore
from app.core.db import get_engine


async def calculate_bolus_for_bot(
    payload: BolusRequestV2,
    *,
    username: str,
) -> BolusResponseV2:
    settings = get_settings()
    store = DataStore(Path(settings.data.data_dir))

    user = _resolve_user(username, settings.data.data_dir)

    engine = get_engine()
    if engine is None:
        raise RuntimeError("Database engine not available")

    async with AsyncSession(engine) as session:
        return await calculate_bolus_stateless_service(
            payload,
            store=store,
            user=user,
            session=session,
        )


def _resolve_user(username: str, data_dir: str) -> CurrentUser:
    store = UserStore(Path(data_dir) / "users.json")
    record = store.find(username) if username else None
    if record:
        return CurrentUser(**record)
    return CurrentUser(username=username or "admin", role="admin")
