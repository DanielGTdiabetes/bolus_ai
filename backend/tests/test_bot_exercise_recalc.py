import pytest

from app.bot import service
from app.models.bolus_v2 import BolusRequestV2
from app.models.settings import UserSettings


@pytest.mark.asyncio
async def test_exercise_recalc_without_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = UserSettings()
    req = BolusRequestV2(
        carbs_g=0,
        target_mgdl=settings.targets.mid,
        meal_slot="lunch",
    )
    req.exercise.planned = True
    req.exercise.minutes = 30
    req.exercise.intensity = "moderate"

    captured = {}
    sentinel = object()

    async def fake_calc(payload: BolusRequestV2, *, username: str) -> object:
        captured["username"] = username
        return sentinel

    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calc)

    result = await service._calculate_bolus_with_context(
        req,
        user_settings=settings,
        resolved_user_id=None,
        snapshot_user_id=None,
    )

    assert result is sentinel
    assert captured["username"] == "admin"


@pytest.mark.asyncio
async def test_exercise_recalc_prefers_snapshot_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = UserSettings()
    req = BolusRequestV2(
        carbs_g=0,
        target_mgdl=settings.targets.mid,
        meal_slot="lunch",
    )

    captured = {}
    sentinel = object()

    async def fake_calc(payload: BolusRequestV2, *, username: str) -> object:
        captured["username"] = username
        return sentinel

    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calc)

    result = await service._calculate_bolus_with_context(
        req,
        user_settings=settings,
        resolved_user_id="admin",
        snapshot_user_id="dani",
    )

    assert result is sentinel
    assert captured["username"] == "dani"


@pytest.mark.asyncio
async def test_exercise_recalc_uses_resolved_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = UserSettings()
    req = BolusRequestV2(
        carbs_g=0,
        target_mgdl=settings.targets.mid,
        meal_slot="lunch",
    )

    captured = {}
    sentinel = object()

    async def fake_calc(payload: BolusRequestV2, *, username: str) -> object:
        captured["username"] = username
        return sentinel

    monkeypatch.setattr(service, "calculate_bolus_for_bot", fake_calc)

    result = await service._calculate_bolus_with_context(
        req,
        user_settings=settings,
        resolved_user_id="dani",
        snapshot_user_id=None,
    )

    assert result is sentinel
    assert captured["username"] == "dani"
