from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from telegram.error import BadRequest, RetryAfter, TimedOut

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
        total_u_final = 4.1
        total_u_raw = 2.71
        kind = "dual"
        upfront_u = 2.7
        later_u = 1.4
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

    assert "Resultado total: **4.1 U**" in sent["text"]
    assert "Dosis inmediata: **2.7 U**" in sent["text"]
    assert "Planificada para revisar tras 240 min: **1.4 U**" in sent["text"]
    button_texts = [
        button.text
        for row in sent["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "✅ Poner 2.7 U" in button_texts
    assert "✅ Poner 4.1 U" not in button_texts


def test_telegram_timeout_is_ambiguous_and_never_blindly_retried() -> None:
    result = service._classify_nutrition_delivery_error(TimedOut("timeout after send"))

    assert result.status == "delivery_unknown"
    assert result.retry_after_seconds is None


def test_telegram_retry_after_is_safe_to_schedule() -> None:
    result = service._classify_nutrition_delivery_error(RetryAfter(37))

    assert result.status == "retry_scheduled"
    assert result.retry_after_seconds == 37


def test_telegram_bad_request_is_terminal() -> None:
    result = service._classify_nutrition_delivery_error(BadRequest("invalid payload"))

    assert result.status == "failed"


@pytest.mark.asyncio
async def test_notification_preparation_error_is_safe_to_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_before_delivery(*args, **kwargs):
        raise RuntimeError("calculator unavailable")

    monkeypatch.setattr(service, "on_new_meal_received", fail_before_delivery)

    result = await service.deliver_nutrition_notification({"carbs": 10})

    assert result.status == "retry_scheduled"
    assert result.error == "pre_delivery:calculator unavailable"
