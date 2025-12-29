import asyncio

import pytest

from app.bot import tools
from app.models.settings import UserSettings


@pytest.mark.asyncio
async def test_tool_catalog_contains_core_tools():
    names = {t["name"] for t in tools.AI_TOOL_DECLARATIONS}
    for required in [
        "get_status_context",
        "calculate_bolus",
        "calculate_correction",
        "simulate_whatif",
        "get_nightscout_stats",
        "set_temp_mode",
        "add_treatment",
    ]:
        assert required in names


@pytest.mark.asyncio
async def test_calculate_correction_uses_status(monkeypatch):
    dummy_settings = UserSettings.default()

    async def fake_load():
        return dummy_settings

    async def fake_status(user_settings=None):
        return tools.StatusContext(bg_mgdl=200, delta=1.0, iob_u=1.0, cob_g=0, quality="live", source="test")

    monkeypatch.setattr(tools, "_load_user_settings", fake_load)
    monkeypatch.setattr(tools, "get_status_context", fake_status)

    res = await tools.calculate_correction()
    assert res.units >= 0
    assert res.explanation
