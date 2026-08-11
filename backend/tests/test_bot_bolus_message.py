from types import SimpleNamespace

import pytest

from app.bot import service as bot_service
from app.bot.service import _build_bolus_message
from app.models.settings import UserSettings


def _rec(
    *, meal=2.0, correction=0.0, iob=0.0, total=2.0, target=110.0,
    kind="normal", upfront=None, later=0.0, duration=0,
):
    return SimpleNamespace(
        total_u_final=total,
        meal_bolus_u=meal,
        correction_u=correction,
        iob_u=iob,
        used_params=SimpleNamespace(target_mgdl=target),
        kind=kind,
        upfront_u=total if upfront is None else upfront,
        later_u=later,
        duration_min=duration,
        explain=[],
    )


def test_bot_message_does_not_present_iob_as_subtracted_from_new_carbs():
    text, _, _ = _build_bolus_message(
        _rec(meal=2.0, correction=0.0, iob=3.5, total=2.0),
        carbs=20,
        fat=0,
        protein=0,
        bg_val=110,
        request_id="abc123",
        notes="",
    )

    assert "IOB activo: 3.50 U" in text
    assert "aplicado a corrección: 0.00 U" in text
    assert "IOB: −3.50 U" not in text
    assert "Ajuste/Redondeo" not in text


def test_bot_message_reports_only_iob_actually_allocated_to_positive_correction():
    text, _, _ = _build_bolus_message(
        _rec(meal=2.0, correction=2.0, iob=1.0, total=3.0),
        carbs=20,
        fat=0,
        protein=0,
        bg_val=170,
        request_id="abc124",
        notes="",
    )

    assert "IOB activo: 1.00 U" in text
    assert "aplicado a corrección: 1.00 U" in text
    assert "corrección restante: 1.00 U" in text


def test_bot_message_zero_iob_is_described_as_active_state_not_subtraction():
    text, _, _ = _build_bolus_message(
        _rec(meal=2.0, correction=0.0, iob=0.0, total=2.0),
        carbs=20,
        fat=0,
        protein=0,
        bg_val=110,
        request_id="abc125",
        notes="",
    )

    assert "IOB activo: 0.00 U" in text
    assert "IOB: −0.0 U" not in text


def test_bot_message_separates_total_immediate_and_planned_later_dose():
    text, _, _ = _build_bolus_message(
        _rec(total=5.0, kind="dual", upfront=3.5, later=1.5, duration=240),
        carbs=29,
        fat=65,
        protein=30,
        bg_val=91,
        request_id="warsaw1",
        notes="",
    )

    assert "Sugerencia total: **5 U**" in text
    assert "Dosis inmediata: **3.5 U**" in text
    assert "Planificada para revisar más tarde: **1.5 U**" in text


@pytest.mark.asyncio
async def test_hydrated_bolus_snapshot_leaves_target_to_central_slot_resolution(monkeypatch):
    settings = UserSettings.default()
    settings.targets.mid = 110
    settings.targets.lunch = 105

    async def fake_settings(*args, **kwargs):
        return settings, "tester"

    monkeypatch.setattr(bot_service, "get_bot_user_settings_with_user_id", fake_settings)
    monkeypatch.setattr(bot_service, "get_current_meal_slot", lambda _settings: "lunch")

    snapshot = await bot_service._hydrate_bolus_snapshot({
        "id": "req1",
        "type": "bolus",
        "carbs": 20,
    })

    assert snapshot["payload"].meal_slot == "lunch"
    assert snapshot["payload"].target_mgdl is None
