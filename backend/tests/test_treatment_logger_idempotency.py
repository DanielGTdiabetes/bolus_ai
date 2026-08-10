from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

import pytest

from app.core.db import get_engine
from app.models.treatment import Treatment
from app.models.settings import UserSettings
from app.services.iob import compute_iob_from_sources
from app.services.store import DataStore
from app.services.treatment_logger import log_treatment


@pytest.mark.asyncio
async def test_retried_treatment_identity_is_persisted_once(monkeypatch, tmp_path):
    async def no_ns(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.treatment_logger.get_ns_config", no_ns)
    treatment_id = "bolus-idempotent-123"
    store = DataStore(tmp_path)

    async with AsyncSession(get_engine()) as session:
        first = await log_treatment(
            "admin",
            treatment_id=treatment_id,
            insulin=2,
            carbs=20,
            store=store,
            session=session,
        )
        second = await log_treatment(
            "admin",
            treatment_id=treatment_id,
            insulin=2,
            carbs=20,
            store=store,
            session=session,
        )
        count = await session.scalar(
            select(func.count()).select_from(Treatment).where(Treatment.id == treatment_id)
        )

    matching_events = [
        event for event in store.load_events()
        if (event.get("id") or event.get("_id")) == treatment_id
    ]
    assert first.ok and second.ok
    assert count == 1
    assert len(matching_events) == 1

    iob, breakdown, info, warning = await compute_iob_from_sources(
        datetime.now(timezone.utc),
        UserSettings(),
        None,
        store,
        user_id="admin",
        persist_cache=False,
    )
    matching_breakdown = [item for item in breakdown if item.get("id") == treatment_id]
    assert iob is not None and iob > 0
    assert len(matching_breakdown) == 1
    assert info.status == "ok"
    assert warning is None
