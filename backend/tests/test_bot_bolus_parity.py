from types import SimpleNamespace

import pytest

from app.bot import tools
from app.models.settings import UserSettings


def _fake_response(*, total=2.0, target=105.0):
    return SimpleNamespace(
        total_u=total,
        total_u_final=total,
        explain=["motor central"],
        warnings=[],
        glucose=SimpleNamespace(mgdl=120.0, age_minutes=2.0),
        used_params=SimpleNamespace(config_hash="abcdef123456", target_mgdl=target),
        kind="normal",
        upfront_u=total,
        later_u=0.0,
        duration_min=0,
    )


@pytest.mark.asyncio
async def test_bot_meal_leaves_default_target_to_central_engine(monkeypatch):
    settings = UserSettings.default()
    settings.targets.mid = 110
    settings.targets.breakfast = 105
    captured = {}

    async def fake_resolver(*args, **kwargs):
        return settings, "tester"

    async def fake_calculator(payload, *, username):
        captured["payload"] = payload
        captured["username"] = username
        return _fake_response(target=105)

    monkeypatch.setattr(tools, "resolve_bot_user_settings", fake_resolver)
    monkeypatch.setattr(tools, "calculate_bolus_for_bot", fake_calculator)

    result = await tools.calculate_bolus(20, meal_type="breakfast")

    assert result.units == 2.0
    assert captured["username"] == "tester"
    assert captured["payload"].meal_slot == "breakfast"
    assert captured["payload"].target_mgdl is None


@pytest.mark.asyncio
async def test_bot_meal_preserves_explicit_target_override(monkeypatch):
    settings = UserSettings.default()
    captured = {}

    async def fake_resolver(*args, **kwargs):
        return settings, "tester"

    async def fake_calculator(payload, *, username):
        captured["payload"] = payload
        return _fake_response(target=115)

    monkeypatch.setattr(tools, "resolve_bot_user_settings", fake_resolver)
    monkeypatch.setattr(tools, "calculate_bolus_for_bot", fake_calculator)

    await tools.calculate_bolus(20, meal_type="breakfast", target=115)

    assert captured["payload"].target_mgdl == 115


@pytest.mark.asyncio
async def test_bot_correction_delegates_to_authoritative_bolus_engine(monkeypatch):
    settings = UserSettings.default()
    settings.targets.breakfast = 105
    captured = {}

    async def fake_resolver(*args, **kwargs):
        return settings, "tester"

    async def fake_calculator(payload, *, username):
        captured["payload"] = payload
        captured["username"] = username
        return _fake_response(total=0.75, target=105)

    monkeypatch.setattr(tools, "resolve_bot_user_settings", fake_resolver)
    monkeypatch.setattr(tools, "_resolve_meal_slot", lambda _settings, _meal_type=None: "breakfast")
    monkeypatch.setattr(tools, "calculate_bolus_for_bot", fake_calculator)

    result = await tools.calculate_correction()

    assert result.units == 0.75
    assert captured["username"] == "tester"
    assert captured["payload"].carbs_g == 0
    assert captured["payload"].meal_slot == "breakfast"
    assert captured["payload"].target_mgdl is None
    assert "motor central" in result.explanation


@pytest.mark.asyncio
async def test_bot_correction_preserves_explicit_target_override(monkeypatch):
    settings = UserSettings.default()
    captured = {}

    async def fake_resolver(*args, **kwargs):
        return settings, "tester"

    async def fake_calculator(payload, *, username):
        captured["payload"] = payload
        return _fake_response(total=0.5, target=120)

    monkeypatch.setattr(tools, "resolve_bot_user_settings", fake_resolver)
    monkeypatch.setattr(tools, "_resolve_meal_slot", lambda _settings, _meal_type=None: "lunch")
    monkeypatch.setattr(tools, "calculate_bolus_for_bot", fake_calculator)

    await tools.calculate_correction(target_bg=120)

    assert captured["payload"].target_mgdl == 120
