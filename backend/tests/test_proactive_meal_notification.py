from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from app.bot import service, tools
from app.models.settings import UserSettings


@pytest.mark.asyncio
async def test_proactive_meal_notification_fallback_username(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    sent = {}

    async def fake_bot_send(*, chat_id: int, text: str, bot=None, **kwargs):
        sent["chat_id"] = chat_id
        sent["text"] = text
        sent["bot"] = bot
        return SimpleNamespace(message_id=123)

    async def fake_resolve_bot_user_settings(preferred_username=None):
        return UserSettings(), "admin"

    async def fake_get_status_context(*args, **kwargs):
        return tools.BolusContext(
            bg_mgdl=120.0,
            iob_u=0.0,
            direction=None,
            source="mock",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    class DummyRec:
        total_u_final = 1.0
        total_u_raw = 1.0
        explain = ["mock explain"]

    async def fake_calculate_bolus_for_bot(*args, **kwargs):
        return DummyRec()

    monkeypatch.setattr(service.config, "get_allowed_telegram_user_id", lambda: 123)
    monkeypatch.setattr(service, "_bot_app", SimpleNamespace(bot=object()))
    monkeypatch.setattr(service, "bot_send", fake_bot_send)
    monkeypatch.setattr(service, "resolve_bot_user_settings", fake_resolve_bot_user_settings)
    monkeypatch.setattr(service.tools, "get_status_context", fake_get_status_context)
    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calculate_bolus_for_bot)

    caplog.set_level("INFO")

    await service.on_new_meal_received(10.0, 0.0, 0.0, 0.0, "mfp", origin_id="abc123")

    assert sent["chat_id"] == 123
    assert "Nueva Comida Detectada" in sent["text"]
    assert "proactive_meal_username_fallback" in caplog.text
