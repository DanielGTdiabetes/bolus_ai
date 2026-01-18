import asyncio

import pytest

from app.bot import tools
from app.bot import service as bot_service
from app.models.settings import UserSettings
from app.services import treatment_logger


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


class _DummyStore:
    def __init__(self):
        self.payloads = {}

    def load_events(self):
        return []

    def save_events(self, events):
        self.payloads["events"] = events

    def read_json(self, filename, default):
        return self.payloads.get(filename, default)

    def write_json(self, filename, data):
        self.payloads[filename] = data


@pytest.mark.asyncio
async def test_add_treatment_calls_logger(monkeypatch):
    called = {}

    async def fake_logger(**kwargs):
        called["kwargs"] = kwargs
        return treatment_logger.TreatmentLogResult(
            ok=True,
            treatment_id="abc",
            insulin=kwargs.get("insulin"),
            carbs=kwargs.get("carbs"),
            saved_local=True,
        )

    async def fake_resolve_user_id(session=None):
        return "tester"

    monkeypatch.setattr(tools, "log_treatment", fake_logger)
    monkeypatch.setattr(tools, "_resolve_user_id", fake_resolve_user_id)
    monkeypatch.setattr(tools, "DataStore", lambda *args, **kwargs: _DummyStore())
    monkeypatch.setattr(
        tools,
        "get_settings",
        lambda: type("Cfg", (), {"data": type("D", (), {"data_dir": "/tmp"})()})(),
    )

    result = await tools.add_treatment({"carbs": 12, "insulin": 1.2, "notes": "unit test"})

    assert called["kwargs"]["carbs"] == 12
    assert called["kwargs"]["insulin"] == 1.2
    assert isinstance(result, tools.AddTreatmentResult)
    assert result.ok is True


class DummyQuery:
    def __init__(self, data: str, text: str):
        self.data = data
        self.message = type("Msg", (), {"text": text})
        self.from_user = type("User", (), {"id": 1})()
        self.answered = False
        self.edits = []

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text: str, **kwargs):
        self.edits.append(text)


class DummyContext:
    bot = None


@pytest.mark.asyncio
async def test_callback_accept_uses_add_treatment(monkeypatch):
    calls = {}

    async def fake_add_treatment(args):
        calls["args"] = args
        return tools.AddTreatmentResult(ok=True, treatment_id="t1", insulin=args.get("insulin"), carbs=args.get("carbs"))

    monkeypatch.setattr(tools, "add_treatment", fake_add_treatment)
    monkeypatch.setattr(bot_service, "DataStore", lambda *a, **k: _DummyStore())
    monkeypatch.setattr(
        bot_service,
        "get_settings",
        lambda: type("Cfg", (), {"data": type("D", (), {"data_dir": "/tmp"})()})(),
    )

    bot_service.SNAPSHOT_STORAGE.clear()
    bot_service.SNAPSHOT_STORAGE["req1"] = {"units": 1.0, "carbs": 15, "notes": "unit test"}

    query = DummyQuery("accept|req1", "Texto base")
    update = type("U", (), {"callback_query": query})
    context = DummyContext()

    await bot_service.handle_callback(update, context)

    assert calls["args"]["insulin"] == 1.0
    assert calls["args"]["carbs"] == 15.0
    assert query.answered is True
    assert any("Registrado ✅" in msg for msg in query.edits)
