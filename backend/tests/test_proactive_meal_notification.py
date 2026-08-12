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
        kind = "normal"
        upfront_u = 1.0
        later_u = 0.0
        duration_min = 0
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
    assert "15 min" in sent["text"]
    assert "proactive_meal_username_fallback" in caplog.text


@pytest.mark.asyncio
async def test_proactive_dual_meal_offers_only_immediate_dose(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = {}

    async def fake_bot_send(*, chat_id: int, text: str, bot=None, **kwargs):
        sent["text"] = text
        sent["reply_markup"] = kwargs.get("reply_markup")
        return SimpleNamespace(message_id=123)

    async def fake_resolve_bot_user_settings(preferred_username=None):
        settings = UserSettings()
        settings.dual_bolus.enabled_default = True
        return settings, "admin"

    async def fake_get_status_context(*args, **kwargs):
        return tools.BolusContext(
            bg_mgdl=91.0,
            iob_u=0.03,
            direction=None,
            source="mock",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    class DummyDualRec:
        total_u_final = 4.0
        total_u_raw = 2.71
        kind = "dual"
        upfront_u = 2.5
        later_u = 1.5
        duration_min = 240
        explain = ["Warsaw Auto-Dual"]

    async def fake_calculate_bolus_for_bot(*args, **kwargs):
        return DummyDualRec()

    monkeypatch.setattr(service.config, "get_allowed_telegram_user_id", lambda: 123)
    monkeypatch.setattr(service, "_bot_app", SimpleNamespace(bot=object()))
    monkeypatch.setattr(service, "bot_send", fake_bot_send)
    monkeypatch.setattr(service, "resolve_bot_user_settings", fake_resolve_bot_user_settings)
    monkeypatch.setattr(service.tools, "get_status_context", fake_get_status_context)
    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calculate_bolus_for_bot)

    await service.on_new_meal_received(29.0, 65.0, 30.0, 0.0, "mfp", origin_id="dual123")

    assert "Resultado total: **4 U**" in sent["text"]
    assert "Dosis inmediata: **2.5 U**" in sent["text"]
    assert "Planificada para revisar tras 240 min: **1.5 U**" in sent["text"]
    button_texts = [
        button.text
        for row in sent["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "✅ Poner 2.5 U" in button_texts
    assert "✅ Poner 4.0 U" not in button_texts


@pytest.mark.asyncio
async def test_proactive_real_warsaw_single_offers_all_now_without_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = {}

    async def fake_bot_send(*, chat_id: int, text: str, bot=None, **kwargs):
        sent["text"] = text
        sent["reply_markup"] = kwargs.get("reply_markup")
        return SimpleNamespace(message_id=124)

    async def fake_resolve_bot_user_settings(preferred_username=None):
        settings = UserSettings()
        settings.round_step_u = 0.5
        settings.dual_bolus.enabled_default = False
        return settings, "admin"

    async def fake_get_status_context(*args, **kwargs):
        return tools.BolusContext(
            bg_mgdl=91.0,
            iob_u=0.03,
            direction=None,
            source="mock",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    class DummySingleRec:
        total_u_final = 4.0
        total_u_raw = 2.71
        kind = "normal"
        upfront_u = 4.0
        later_u = 0.0
        duration_min = 0
        explain = ["Warsaw FPU (INMEDIATA; bolo dual desactivado)"]

    async def fake_calculate_bolus_for_bot(*args, **kwargs):
        return DummySingleRec()

    monkeypatch.setattr(service.config, "get_allowed_telegram_user_id", lambda: 123)
    monkeypatch.setattr(service, "_bot_app", SimpleNamespace(bot=object()))
    monkeypatch.setattr(service, "bot_send", fake_bot_send)
    monkeypatch.setattr(service, "resolve_bot_user_settings", fake_resolve_bot_user_settings)
    monkeypatch.setattr(service.tools, "get_status_context", fake_get_status_context)
    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calculate_bolus_for_bot)

    await service.on_new_meal_received(
        29.0,
        65.0,
        30.0,
        0.0,
        "mfp",
        origin_id="single-4u",
    )

    assert "Resultado total: **4 U**" in sent["text"]
    assert "Dosis inmediata" not in sent["text"]
    assert "Planificada" not in sent["text"]
    button_texts = [
        button.text
        for row in sent["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "✅ Poner 4.0 U" in button_texts
