import pytest

from app.models.bolus_v2 import BolusRequestV2, GlucoseUsed
from app.models.settings import UserSettings
from app.services.bolus_engine import calculate_bolus_v2


def calculate(*, carbs=20, bg=110, target=110, isf=30, icr=10, iob=0, **request_kwargs):
    settings = UserSettings()
    settings.cr.lunch = icr
    settings.cf.lunch = isf
    settings.targets.lunch = target
    settings.round_step_u = request_kwargs.pop("round_step_u", 0.1)
    settings.max_bolus_u = request_kwargs.pop("max_bolus_u", 20)
    request = BolusRequestV2(
        carbs_g=carbs,
        bg_mgdl=bg,
        target_mgdl=target,
        meal_slot="lunch",
        **request_kwargs,
    )
    glucose = GlucoseUsed(mgdl=bg, source="manual")
    return calculate_bolus_v2(request, settings, iob_u=iob, glucose_info=glucose)


def test_autosens_request_override_is_explicit_only():
    assert BolusRequestV2(carbs_g=0).enable_autosens is None
    assert BolusRequestV2(carbs_g=0, enable_autosens=False).enable_autosens is False
    assert BolusRequestV2(carbs_g=0, enable_autosens=True).enable_autosens is True


def test_autosens_changes_effective_ratios_and_exposes_them_for_traceability():
    settings = UserSettings()
    settings.cr.lunch = 10
    settings.cf.lunch = 30
    settings.targets.lunch = 110
    settings.round_step_u = 0.1
    settings.max_bolus_u = 20

    request = BolusRequestV2(
        carbs_g=20,
        bg_mgdl=110,
        meal_slot="lunch",
    )
    glucose = GlucoseUsed(mgdl=110, source="manual")

    result = calculate_bolus_v2(
        request,
        settings,
        iob_u=0,
        glucose_info=glucose,
        autosens_ratio=1.2,
        autosens_reason="regression",
    )

    assert result.total_u == pytest.approx(2.4)
    assert result.used_params.autosens_ratio == 1.2
    assert result.used_params.autosens_reason == "regression"
    assert result.used_params.effective_cr_g_per_u == pytest.approx(8.333, abs=0.001)
    assert result.used_params.effective_isf_mgdl_per_u == 25.0
    assert any("Autosens" in line for line in result.explain)


def test_meal_without_iob():
    result = calculate(iob=0)
    assert result.meal_bolus_u == 2.0
    assert result.total_u == 2.0


def test_new_carbs_are_not_consumed_by_existing_iob():
    result = calculate(iob=3.5)
    assert result.meal_bolus_u == 2.0
    assert result.correction_u == 0.0
    assert result.total_u == 2.0


def test_removed_ignore_iob_input_is_rejected():
    with pytest.raises(ValueError, match="ignore_iob has been removed"):
        BolusRequestV2.model_validate({"carbs_g": 20, "ignore_iob": True})


@pytest.mark.parametrize("iob,expected", [(0, 4.0), (1, 3.0), (3.5, 2.0)])
def test_iob_offsets_only_positive_correction(iob, expected):
    result = calculate(bg=170, iob=iob)
    assert result.meal_bolus_u == 2.0
    assert result.correction_u == 2.0
    assert result.total_u == expected


def test_iob_still_prevents_correction_stacking():
    result = calculate(carbs=0, bg=170, iob=3.5)
    assert result.meal_bolus_u == 0.0
    assert result.correction_u == 2.0
    assert result.total_u == 0.0


def test_low_bg_adjustment_reduces_meal_without_double_iob_subtraction():
    result = calculate(bg=80, iob=3.5)
    assert result.meal_bolus_u == 2.0
    assert result.correction_u == -1.0
    assert result.total_u == 1.0


def test_hypoglycemia_hard_stop():
    result = calculate(bg=65, iob=0)
    assert result.total_u == 0.0
    assert any("HIPO" in line for line in result.explain)


def test_exercise_reduction():
    result = calculate(
        carbs=10,
        iob=0,
        round_step_u=0.5,
        exercise={"planned": True, "minutes": 60, "intensity": "moderate"},
    )
    assert result.total_u == 0.5


def test_max_bolus_limit():
    result = calculate(carbs=200, max_bolus_u=5)
    assert result.total_u == 5.0


def test_rounding():
    result = calculate(carbs=23, round_step_u=0.5)
    assert result.total_u == 2.5


@pytest.mark.parametrize("elapsed_minutes", [20, 30, 60, 120])
def test_consecutive_meal_keeps_full_new_carb_coverage(elapsed_minutes):
    # The exact pharmacological IOB changes with elapsed time. Its allocation
    # does not: it may offset a correction, never these newly entered carbs.
    from app.services.iob import InsulinActionProfile, insulin_activity_fraction

    profile = InsulinActionProfile(dia_hours=4, curve="walsh", peak_minutes=75)
    iob = 4.0 * insulin_activity_fraction(elapsed_minutes, profile)
    result = calculate(iob=iob)
    assert iob > 0
    assert result.total_u == 2.0
