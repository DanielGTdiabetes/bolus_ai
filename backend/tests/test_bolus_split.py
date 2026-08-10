from datetime import datetime, timedelta, timezone

import pytest

from app.models.bolus_split import (
    BolusParams,
    BolusPlanRequest,
    DualSplit,
    ManualSplit,
    NightscoutConn,
    RecalcSecondRequest,
)
from app.models.bolus_v2 import GlucoseUsed
from app.models.settings import UserSettings
from app.services.bolus_engine import calculate_bolus_v2
from app.services.bolus_split import create_plan, recalc_second
from app.services.iob import InsulinActionProfile, compute_iob


def test_plan_manual_exact():
    result = create_plan(BolusPlanRequest(
        mode="manual",
        total_recommended_u=10,
        manual=ManualSplit(now_u=6, later_u=4, later_after_min=60),
    ))
    assert (result.now_u, result.later_u_planned, result.warnings) == (6, 4, [])


def test_plan_manual_warns_when_sum_differs():
    result = create_plan(BolusPlanRequest(
        mode="manual",
        total_recommended_u=8,
        round_step_u=0.5,
        manual=ManualSplit(now_u=4, later_u=3, later_after_min=60),
    ))
    assert result.warnings


def test_plan_dual_rounding():
    result = create_plan(BolusPlanRequest(
        mode="dual",
        total_recommended_u=10,
        round_step_u=0.5,
        dual=DualSplit(percent_now=33, duration_min=120),
    ))
    assert result.now_u == 3.5
    assert result.later_u_planned == 6.5


def test_recalc_second_legacy_inputs_are_optional():
    request = RecalcSecondRequest(
        later_u_planned=2,
        carbs_additional_g=15,
        meal_slot="dinner",
    )
    assert request.params is None
    assert request.nightscout is None
    assert request.meal_slot == "dinner"


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed_minutes", [20, 30, 60, 120])
async def test_recalc_second_uses_central_settings_and_preserves_new_carbs(mocker, elapsed_minutes):
    now = datetime.now(timezone.utc)
    iob = compute_iob(
        now,
        [{"id": "first-bolus", "ts": (now - timedelta(minutes=elapsed_minutes)).isoformat(), "units": 4}],
        InsulinActionProfile(dia_hours=4, curve="walsh", peak_minutes=75),
    )

    async def central_service(payload, **_kwargs):
        # These are the authoritative backend settings. They intentionally differ
        # from the legacy client params supplied below.
        settings = UserSettings()
        settings.cr.dinner = 10
        settings.cf.dinner = 30
        settings.targets.dinner = 110
        settings.round_step_u = 0.1
        settings.max_bolus_u = 7
        return calculate_bolus_v2(
            payload,
            settings,
            iob_u=iob,
            glucose_info=GlucoseUsed(mgdl=110, source="nightscout"),
        )

    central = mocker.patch(
        "app.services.bolus_split.calculate_bolus_stateless_service",
        side_effect=central_service,
    )
    request = RecalcSecondRequest(
        later_u_planned=2,
        carbs_additional_g=20,
        meal_slot="dinner",
        params=BolusParams(
            cr_g_per_u=50,
            isf_mgdl_per_u=100,
            target_bg_mgdl=150,
            max_bolus_u=20,
            insulin_curve="linear",
        ),
        nightscout=NightscoutConn(url="https://example.invalid", token="legacy-secret"),
    )

    result = await recalc_second(request, store=mocker.Mock(), user=mocker.Mock(), session=mocker.Mock())

    central.assert_awaited_once()
    sent_payload = central.await_args.args[0]
    assert sent_payload.meal_slot == "dinner"
    assert sent_payload.cr_g_per_u is None
    assert sent_payload.isf_mgdl_per_u is None
    assert sent_payload.target_mgdl is None
    assert sent_payload.dia_hours is None
    assert sent_payload.insulin_model is None
    assert sent_payload.round_step_u is None
    assert sent_payload.max_bolus_u is None
    assert sent_payload.nightscout is None
    assert sent_payload.enable_autosens is None

    assert result.iob_now_u == pytest.approx(iob, abs=0.01)
    assert result.components.meal_u == 2.0
    assert result.components.iob_applied_u == 0.0
    assert result.u2_recommended_u == 2.0
    assert result.cap_u == 7
    assert any("planificada" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_recalc_second_does_not_disable_autosens(mocker):
    async def central_service(payload, **_kwargs):
        assert payload.enable_autosens is None
        settings = UserSettings()
        settings.cr.lunch = 10
        settings.cf.lunch = 30
        settings.targets.lunch = 110
        settings.round_step_u = 0.1
        settings.max_bolus_u = 20
        # Simulate what the central service supplies when the saved Autosens
        # setting is enabled and resolves a 1.20 ratio.
        return calculate_bolus_v2(
            payload,
            settings,
            iob_u=0,
            glucose_info=GlucoseUsed(mgdl=110, source="nightscout"),
            autosens_ratio=1.2,
            autosens_reason="split regression",
        )

    central = mocker.patch(
        "app.services.bolus_split.calculate_bolus_stateless_service",
        side_effect=central_service,
    )

    result = await recalc_second(
        RecalcSecondRequest(
            later_u_planned=0,
            carbs_additional_g=20,
            meal_slot="lunch",
        ),
        store=mocker.Mock(),
        user=mocker.Mock(),
        session=mocker.Mock(),
    )

    central.assert_awaited_once()
    assert result.components.meal_u == pytest.approx(2.4)
    assert result.u2_recommended_u == pytest.approx(2.4)
