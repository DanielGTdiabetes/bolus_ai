from app.models.bolus_v2 import BolusRequestV2, GlucoseUsed
from app.models.settings import UserSettings
from app.services.bolus_engine import calculate_bolus_v2


def _glucose(mgdl: float = 120.0) -> GlucoseUsed:
    return GlucoseUsed(mgdl=mgdl, source="manual")


def test_target_resolution_mid_fallback():
    settings = UserSettings()
    settings.targets.mid = 115

    req = BolusRequestV2(carbs_g=0.0, meal_slot="lunch")
    res = calculate_bolus_v2(req, settings, iob_u=0.0, glucose_info=_glucose())

    assert res.used_params.target_mgdl == 115


def test_target_resolution_slot_target():
    settings = UserSettings()
    settings.targets.mid = 115
    settings.targets.breakfast = 105

    req = BolusRequestV2(carbs_g=0.0, meal_slot="breakfast")
    res = calculate_bolus_v2(req, settings, iob_u=0.0, glucose_info=_glucose())

    assert res.used_params.target_mgdl == 105


def test_target_resolution_slot_missing_fallback():
    settings = UserSettings()
    settings.targets.mid = 112

    req = BolusRequestV2(carbs_g=0.0, meal_slot="snack")
    res = calculate_bolus_v2(req, settings, iob_u=0.0, glucose_info=_glucose())

    assert res.used_params.target_mgdl == 112
