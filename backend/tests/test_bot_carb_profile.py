from sqlalchemy import select

import pytest

from app.bot import tools
from app.core.db import get_db_session_context
from app.models.treatment import Treatment


@pytest.mark.asyncio
async def test_bot_add_treatment_persists_carb_profile(monkeypatch):
    async def fake_resolve_user_id(session=None):
        return "admin"

    monkeypatch.setattr(tools, "_resolve_user_id", fake_resolve_user_id)

    result = await tools.add_treatment(
        {"carbs": 20, "insulin": 2, "notes": "unit test", "carb_profile": "med"}
    )

    assert result.ok is True

    async with get_db_session_context() as session:
        row = (await session.execute(select(Treatment).where(Treatment.id == result.treatment_id))).scalar_one()
        assert row.carb_profile == "med"
