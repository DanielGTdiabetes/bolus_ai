from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from telegram.error import BadRequest, RetryAfter, TimedOut

from app.bot import service, tools
from app.models.settings import UserSettings
from app.services import companion_service, meal_coverage_service


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
async def test_updated_meal_message_and_calculator_use_only_incremental_macros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = {}
    calculated = {}
    recorded_episode = {}
    delivery_order = []

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return False

    state = SimpleNamespace(
        id="state-1",
        meal_key="meal-key",
        external_meal_id="myfitnesspal|lunch-1",
        current_revision="revision-2",
        revision_number=2,
        current_nutrition={"carbs": 87, "fat": 15, "protein": 25, "fiber": 5},
        covered_nutrition={"carbs": 63, "fat": 10, "protein": 20, "fiber": 4},
        last_confirmed_bolus=8.0,
        confirmed_at=datetime.now(timezone.utc),
        last_calculation_id="calc-1",
    )

    async def fake_get_meal_state(*args, **kwargs):
        return state

    async def fake_bot_send(*, chat_id: int, text: str, bot=None, **kwargs):
        sent["text"] = text
        delivery_order.append("telegram_delivered")
        return SimpleNamespace(message_id=321)

    async def fake_resolve_bot_user_settings(preferred_username=None):
        return UserSettings(), "admin"

    async def fake_get_status_context(*args, **kwargs):
        return tools.BolusContext(
            bg_mgdl=160.0,
            iob_u=7.93,
            direction=None,
            source="mock",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    class DummyRec:
        total_u_final = 3.2
        total_u_raw = 3.2
        kind = "normal"
        upfront_u = 3.2
        later_u = 0.0
        duration_min = 0
        explain = ["A) Comida: 24g / 7.5 = 3.20 U"]

    async def fake_calculate_bolus_for_bot(request, **kwargs):
        calculated["request"] = request
        return DummyRec()

    async def fake_get_episode_by_fingerprint(user_id, fingerprint, session):
        if fingerprint == "meal_detected:draft-1":
            return SimpleNamespace(status="monitoring")
        return None

    async def fake_record_meal_episode(user_id, origin_id, message, context, session):
        recorded_episode["origin_id"] = origin_id
        delivery_order.append("current_recorded")
        return SimpleNamespace(status="monitoring")

    async def fake_resolve_superseded(
        user_id, origin_id, current_episode_origin_id, session
    ):
        delivery_order.append("prior_resolved")
        return 1

    monkeypatch.setattr(service.config, "get_allowed_telegram_user_id", lambda: 123)
    monkeypatch.setattr(service, "_bot_app", SimpleNamespace(bot=object()))
    monkeypatch.setattr(service, "SessionLocal", lambda: SessionContext())
    monkeypatch.setattr(service, "bot_send", fake_bot_send)
    monkeypatch.setattr(service, "resolve_bot_user_settings", fake_resolve_bot_user_settings)
    monkeypatch.setattr(service.tools, "get_status_context", fake_get_status_context)
    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calculate_bolus_for_bot)
    monkeypatch.setattr(service, "get_current_meal_slot", lambda _settings: "lunch")
    monkeypatch.setattr(meal_coverage_service, "get_meal_state", fake_get_meal_state)
    monkeypatch.setattr(
        companion_service, "get_episode_by_fingerprint", fake_get_episode_by_fingerprint
    )
    monkeypatch.setattr(companion_service, "record_meal_episode", fake_record_meal_episode)
    monkeypatch.setattr(
        companion_service,
        "resolve_superseded_meal_episodes",
        fake_resolve_superseded,
    )

    await service.on_new_meal_received(
        87,
        15,
        25,
        5,
        "Actualizado (admin)",
        origin_id="draft-1",
        meal_id="myfitnesspal|lunch-1",
        meal_revision="revision-2",
        meal_user_id="admin",
        meal_slot="breakfast",
    )

    request = calculated["request"]
    assert (request.carbs_g, request.fat_g, request.protein_g, request.fiber_g) == (
        24,
        5,
        5,
        1,
    )
    assert request.meal_slot == "breakfast"
    assert "Comida actualizada" in sent["text"]
    assert "Total comida: **87 g HC**" in sent["text"]
    assert "Ya cubiertos: **63 g HC**" in sent["text"]
    assert "Nuevos: **+24 g HC**" in sent["text"]
    assert "Bolo previo confirmado: **8 U** hace" in sent["text"]
    assert "Resultado adicional: **3.2 U**" in sent["text"]
    assert recorded_episode["origin_id"] == "draft-1:revision-2"
    assert delivery_order == [
        "telegram_delivered",
        "prior_resolved",
        "current_recorded",
    ]


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
