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


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed_minutes", [20, 30, 60, 120])
async def test_recalc_second_uses_central_engine_and_preserves_new_carbs(mocker, elapsed_minutes):
    now = datetime.now(timezone.utc)
    iob = compute_iob(
        now,
        [{"id": "first-bolus", "ts": (now - timedelta(minutes=elapsed_minutes)).isoformat(), "units": 4}],
        InsulinActionProfile(dia_hours=4, curve="walsh", peak_minutes=75),
    )

    async def central_service(payload, **_kwargs):
        settings = UserSettings()
        settings.cr.lunch = 10
        settings.cf.lunch = 30
        settings.targets.lunch = 110
        settings.round_step_u = 0.1
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
        params=BolusParams(cr_g_per_u=10, isf_mgdl_per_u=30, target_bg_mgdl=110),
        nightscout=NightscoutConn(url="https://example.invalid"),
    )

    result = await recalc_second(request, store=mocker.Mock(), user=mocker.Mock(), session=mocker.Mock())

    central.assert_awaited_once()
    assert result.iob_now_u == pytest.approx(iob, abs=0.01)
    assert result.components.meal_u == 2.0
    assert result.components.iob_applied_u == 0.0
    assert result.u2_recommended_u == 2.0
