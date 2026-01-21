import types

import pytest

from app.bot import service
from app.models.bolus_v2 import BolusRequestV2
from app.models.settings import UserSettings


class DummyUser:
    def __init__(self, user_id: int = 1, username: str = "tester") -> None:
        self.id = user_id
        self.username = username


class DummyChat:
    def __init__(self, chat_id: int = 123) -> None:
        self.id = chat_id


class DummyMessage:
    def __init__(self, text: str = "msg", chat_id: int = 123) -> None:
        self.text = text
        self.chat_id = chat_id


class DummyCallbackQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.from_user = DummyUser()
        self.message = DummyMessage()

    async def answer(self, *args, **kwargs) -> None:
        return None


class DummyUpdate:
    def __init__(self, data: str) -> None:
        self.callback_query = DummyCallbackQuery(data)
        self.effective_user = self.callback_query.from_user
        self.effective_chat = DummyChat()


@pytest.fixture(autouse=True)
def _clear_snapshots() -> None:
    service.SNAPSHOT_STORAGE.clear()


@pytest.mark.asyncio
async def test_accept_manual_without_snapshot_includes_units(monkeypatch: pytest.MonkeyPatch) -> None:
    req_id = "req-123"
    units = 2.5
    update = DummyUpdate(f"accept_manual|{units}|{req_id}")
    context = types.SimpleNamespace(user_data={}, bot=object())

    captured = {"edited": [], "add_args": None}

    async def fake_edit_message_text_safe(_query, text: str, **_kwargs):
        captured["edited"].append(text)

    async def fake_add_treatment(args):
        captured["add_args"] = args
        return types.SimpleNamespace(ok=True, treatment_id=None, injection_site=None)

    monkeypatch.setattr(service, "edit_message_text_safe", fake_edit_message_text_safe)
    monkeypatch.setattr(service.tools, "add_treatment", fake_add_treatment)

    await service.handle_callback(update, context)

    assert captured["add_args"] is not None
    assert captured["add_args"]["insulin"] == units
    assert all("Snapshot irreconocible" not in text for text in captured["edited"])


@pytest.mark.asyncio
async def test_macro_edit_prefers_snapshot_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = UserSettings()
    req_id = "meal-456"
    req_v2 = BolusRequestV2(
        carbs_g=5,
        fat_g=0,
        protein_g=0,
        meal_slot="lunch",
        target_mgdl=settings.targets.mid,
    )
    service.SNAPSHOT_STORAGE[req_id] = {
        "payload": req_v2,
        "rec": object(),
        "carbs": 5,
        "fat": 0.0,
        "protein": 0.0,
        "user_id": "snapshot_user",
    }

    update = DummyUpdate("noop")
    context = types.SimpleNamespace(user_data={"editing_meal_request": req_id}, bot=object())

    captured = {}

    async def fake_get_bot_user_settings() -> UserSettings:
        return settings

    async def fake_get_bot_user_settings_with_user_id():
        return settings, "resolved_user"

    async def fake_calc(_payload: BolusRequestV2, *, username: str):
        captured["username"] = username
        return types.SimpleNamespace(total_u_final=1.5, explain=[])

    async def fake_reply_text(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(service, "get_bot_user_settings", fake_get_bot_user_settings)
    monkeypatch.setattr(service, "get_bot_user_settings_with_user_id", fake_get_bot_user_settings_with_user_id)
    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calc)
    monkeypatch.setattr(service, "reply_text", fake_reply_text)

    await service._process_text_input_internal(update, context, "10 0 0")

    snapshot = service.SNAPSHOT_STORAGE[req_id]
    assert captured["username"] == "snapshot_user"
    assert snapshot["payload"].carbs_g == 10.0
    assert snapshot["payload"].fat_g == 0.0
    assert snapshot["payload"].protein_g == 0.0


@pytest.mark.asyncio
async def test_set_slot_recalc_uses_snapshot_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = UserSettings()
    req_id = "slot-789"
    req_v2 = BolusRequestV2(
        carbs_g=12,
        fat_g=0,
        protein_g=0,
        meal_slot="breakfast",
        target_mgdl=settings.targets.mid,
    )
    service.SNAPSHOT_STORAGE[req_id] = {
        "payload": req_v2,
        "rec": object(),
        "carbs": 12,
        "fat": 0.0,
        "protein": 0.0,
        "user_id": "snapshot_user",
    }

    update = DummyUpdate(f"set_slot|lunch|{req_id}")
    context = types.SimpleNamespace(user_data={}, bot=object())

    captured = {}

    async def fake_get_bot_user_settings_with_user_id():
        return settings, "resolved_user"

    async def fake_calc(_payload: BolusRequestV2, *, username: str):
        captured["username"] = username
        return types.SimpleNamespace(total_u_final=2.0, total_u_raw=2.0, explain=[])

    async def fake_edit_message_text_safe(_query, *_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(service, "get_bot_user_settings_with_user_id", fake_get_bot_user_settings_with_user_id)
    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calc)
    monkeypatch.setattr(service, "edit_message_text_safe", fake_edit_message_text_safe)

    await service.handle_callback(update, context)

    snapshot = service.SNAPSHOT_STORAGE[req_id]
    assert captured["username"] == "snapshot_user"
    assert snapshot["payload"].meal_slot == "lunch"
