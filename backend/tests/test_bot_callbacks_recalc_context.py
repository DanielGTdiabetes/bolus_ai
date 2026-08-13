import types

import pytest

from app.bot import service
from app.models.bolus_v2 import (
    BolusRequestV2,
    BolusResponseV2,
    GlucoseUsed,
    UsedParams,
)
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


def _dual_response() -> BolusResponseV2:
    return BolusResponseV2(
        total_u=4.0,
        total_u_final=4.0,
        total_u_raw=2.71,
        kind="dual",
        upfront_u=2.5,
        later_u=1.5,
        duration_min=240,
        iob_u=0.03,
        iob_applied_to_correction_u=0.0,
        meal_bolus_u=2.87,
        correction_u=-0.16,
        glucose=GlucoseUsed(mgdl=91, source="manual"),
        used_params=UsedParams(
            cr_g_per_u=9,
            isf_mgdl_per_u=80,
            target_mgdl=105,
            dia_hours=4,
            max_bolus_final=10,
            effective_cr_g_per_u=10.1,
            effective_isf_mgdl_per_u=89,
            round_step_u=0.5,
            autosens_ratio=0.89,
            dual_bolus_enabled=True,
            config_hash="40ade01676afe08c1c73fab9142bca239039b36449418b4d22cbbb4b861c1f81",
        ),
        explain=["Warsaw Auto-Dual"],
        warnings=[],
    )


def _single_response() -> BolusResponseV2:
    response = _dual_response().model_copy(deep=True)
    response.kind = "normal"
    response.upfront_u = 4.0
    response.later_u = 0.0
    response.duration_min = 0
    response.used_params.dual_bolus_enabled = False
    response.used_params.config_hash = "24a6330dcc1f6ff1467a25a6dc033dde04f1c4b4573b1c9956a51322d2693997"
    response.explain = ["Warsaw FPU (INMEDIATA; bolo dual desactivado)"]
    return response


def test_manual_dual_keyboard_carries_configured_later_delay() -> None:
    settings = UserSettings()
    settings.dual_bolus.percent_now = 60
    settings.dual_bolus.later_after_minutes = 75

    keyboard = service._build_bolus_recommendation_keyboard(
        None,
        request_id="dual-123",
        rec_u=5.0,
        user_settings=settings,
        fiber_dual_rec=True,
    )

    dual_button = next(
        button
        for row in keyboard
        for button in row
        if button.callback_data.startswith("accept_dual|")
    )
    assert dual_button.callback_data == "accept_dual|dual-123|3.0|2.0|75"


@pytest.fixture(autouse=True)
def _isolated_snapshots(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = service.SnapshotStore(tmp_path)
    monkeypatch.setattr(service, "_snapshot_store", store)


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
async def test_accept_engine_dual_records_only_upfront_and_persists_plan(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    req_id = "warsaw-1"
    query = DummyCallbackQuery(f"accept|{req_id}")
    service._get_snapshot_store().set(req_id, {
        "rec": _dual_response(),
        "payload": BolusRequestV2(carbs_g=29, bg_mgdl=123, meal_slot="lunch"),
        "carbs": 29,
        "fat": 65,
        "protein": 30,
        "fiber": 0,
        "source": "mfp",
    })
    captured = {"add_args": None, "plan": None}

    async def fake_add_treatment(args):
        captured["add_args"] = args
        return types.SimpleNamespace(
            ok=True,
            treatment_id="tx-warsaw",
            injection_site=None,
            ns_error=None,
        )

    async def fake_edit_message_text_safe(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service.tools, "add_treatment", fake_add_treatment)
    monkeypatch.setattr(service, "edit_message_text_safe", fake_edit_message_text_safe)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: types.SimpleNamespace(data=types.SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        service,
        "_persist_bot_active_plan",
        lambda _store, plan: captured.update(plan=plan),
    )

    await service._handle_snapshot_callback(query, query.data)

    assert captured["add_args"]["insulin"] == 2.5
    assert captured["add_args"]["duration"] == 0
    # The persisted value must be the glucose actually used by the engine
    # (91 mg/dL), even when the original request contains a different value.
    assert captured["add_args"]["glucose"] == 91.0
    assert captured["plan"]["treatment_id"] == "tx-warsaw"
    assert captured["plan"]["upfront_u"] == 2.5
    assert captured["plan"]["later_u_planned"] == 1.5
    assert captured["plan"]["later_after_min"] == 240


@pytest.mark.asyncio
async def test_accept_real_warsaw_single_records_all_now_and_creates_no_plan(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req_id = "warsaw-single-4u"
    query = DummyCallbackQuery(f"accept|{req_id}")
    service._get_snapshot_store().set(req_id, {
        "rec": _single_response(),
        "payload": BolusRequestV2(carbs_g=29, meal_slot="lunch"),
        "carbs": 29,
        "fat": 65,
        "protein": 30,
        "fiber": 0,
        "source": "mfp",
    })
    captured = {"add_args": None, "plans": []}

    async def fake_add_treatment(args):
        captured["add_args"] = args
        return types.SimpleNamespace(
            ok=True,
            treatment_id="tx-warsaw-single",
            injection_site=None,
            ns_error=None,
        )

    async def fake_edit_message_text_safe(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service.tools, "add_treatment", fake_add_treatment)
    monkeypatch.setattr(service, "edit_message_text_safe", fake_edit_message_text_safe)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: types.SimpleNamespace(data=types.SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        service,
        "_persist_bot_active_plan",
        lambda _store, plan: captured["plans"].append(plan),
    )

    await service._handle_snapshot_callback(query, query.data)

    assert captured["add_args"]["insulin"] == 4.0
    assert captured["add_args"]["duration"] == 0
    assert captured["plans"] == []


@pytest.mark.asyncio
async def test_accept_manual_dual_persists_configured_later_delay(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    req_id = "manual-dual"
    query = DummyCallbackQuery(f"accept_dual|{req_id}|3.0|2.0|75")
    service._get_snapshot_store().set(req_id, {
        "rec": _dual_response(),
        "payload": BolusRequestV2(carbs_g=29, meal_slot="lunch"),
        "carbs": 29,
        "fat": 0,
        "protein": 0,
        "fiber": 10,
        "source": "telegram",
    })
    captured = {"add_args": None, "plan": None}

    async def fake_add_treatment(args):
        captured["add_args"] = args
        return types.SimpleNamespace(
            ok=True,
            treatment_id="tx-manual-dual",
            injection_site=None,
            ns_error=None,
        )

    async def fake_edit_message_text_safe(*_args, **_kwargs):
        return None

    monkeypatch.setattr(service.tools, "add_treatment", fake_add_treatment)
    monkeypatch.setattr(service, "edit_message_text_safe", fake_edit_message_text_safe)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: types.SimpleNamespace(data=types.SimpleNamespace(data_dir=str(tmp_path))),
    )
    monkeypatch.setattr(
        service,
        "_persist_bot_active_plan",
        lambda _store, plan: captured.update(plan=plan),
    )

    await service._handle_snapshot_callback(query, query.data)

    assert captured["add_args"]["insulin"] == 3.0
    assert captured["plan"]["later_u_planned"] == 2.0
    assert captured["plan"]["later_after_min"] == 75


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
    service._get_snapshot_store().set(req_id, {
        "payload": req_v2,
        "rec": object(),
        "carbs": 5,
        "fat": 0.0,
        "protein": 0.0,
        "user_id": "snapshot_user",
    })

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

    snapshot = service._get_snapshot_store().get(req_id)
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
    service._get_snapshot_store().set(req_id, {
        "payload": req_v2,
        "rec": object(),
        "carbs": 12,
        "fat": 0.0,
        "protein": 0.0,
        "user_id": "snapshot_user",
    })

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

    snapshot = service._get_snapshot_store().get(req_id)
    assert captured["username"] == "snapshot_user"
    assert snapshot["payload"].meal_slot == "lunch"
