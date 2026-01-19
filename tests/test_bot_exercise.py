import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.bot import service  # noqa: E402
from app.models.bolus_v2 import BolusRequestV2  # noqa: E402


def _dummy_update() -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(id=456),
    )


def test_bolus_keyboard_includes_exercise_button():
    update = _dummy_update()
    user_settings = SimpleNamespace(dual_bolus=None)

    keyboard = service._build_bolus_recommendation_keyboard(
        update,
        request_id="req123",
        rec_u=1.5,
        user_settings=user_settings,
        fiber_dual_rec=False,
    )

    button_texts = [button.text for row in keyboard for button in row]
    assert "🏃 Añadir ejercicio" in button_texts


class DummyQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=123)
        self.edited_text = None

    async def answer(self, *args, **kwargs) -> None:
        return None

    async def edit_message_text(self, *args, **kwargs) -> None:
        self.edited_text = kwargs.get("text") or (args[0] if args else None)


class DummyContext:
    def __init__(self) -> None:
        self.user_data = {}
        self.bot = SimpleNamespace()


@pytest.mark.asyncio
async def test_exercise_callback_triggers_calc_with_payload(monkeypatch):
    req_id = "req456"
    service.SNAPSHOT_STORAGE[req_id] = {
        "carbs": 10.0,
        "fat": 0.0,
        "protein": 0.0,
        "fiber": 0.0,
        "notes": "",
        "payload": BolusRequestV2(carbs_g=10.0, target_mgdl=100, meal_slot="lunch"),
        "ts": time.time(),
    }

    captured = {}

    async def fake_get_bot_user_settings(*args, **kwargs):
        return SimpleNamespace(
            targets=SimpleNamespace(mid=100),
            dual_bolus=None,
            username="tester",
        )

    async def fake_calculate_bolus_for_bot(req_v2, username):
        captured["request"] = req_v2
        captured["username"] = username
        return SimpleNamespace(total_u_final=1.25, glucose=None)

    async def fake_reply_text(*args, **kwargs):
        return None

    def fake_build_bolus_message(*args, **kwargs):
        return "msg", False, ""

    monkeypatch.setattr(service, "get_bot_user_settings", fake_get_bot_user_settings)
    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calculate_bolus_for_bot)
    monkeypatch.setattr(service, "reply_text", fake_reply_text)
    monkeypatch.setattr(service, "_build_bolus_message", fake_build_bolus_message)

    context = DummyContext()

    start_query = DummyQuery(f"exercise_start|{req_id}")
    update = SimpleNamespace(
        callback_query=start_query,
        effective_user=SimpleNamespace(id=123),
        effective_chat=SimpleNamespace(id=456),
    )
    await service.handle_callback(update, context)
    assert context.user_data["exercise_flow"]["step"] == "level"

    level_query = DummyQuery(f"exercise_level|{req_id}|moderate")
    update.callback_query = level_query
    await service.handle_callback(update, context)
    assert context.user_data["exercise_flow"]["step"] == "duration"

    duration_query = DummyQuery(f"exercise_duration|{req_id}|30")
    update.callback_query = duration_query
    await service.handle_callback(update, context)

    assert "request" in captured
    req_v2 = captured["request"]
    assert req_v2.exercise.planned is True
    assert req_v2.exercise.minutes == 30
    assert req_v2.exercise.intensity == "moderate"
    assert "exercise_flow" not in context.user_data
    service.SNAPSHOT_STORAGE.pop(req_id, None)
