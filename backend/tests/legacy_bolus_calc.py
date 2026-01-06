from app.models.settings import UserSettings
from app.services.bolus import BolusRequestData, recommend_bolus


def _settings():
    settings = UserSettings.default()
    settings.cr.lunch = 10
    settings.cf.lunch = 50
    settings.targets.mid = 100
    settings.max_bolus_u = 15
    settings.max_correction_u = 6
    settings.round_step_u = 0.05
    return settings


def test_bolus_calc_basic():
    settings = _settings()
    request = BolusRequestData(carbs_g=60, bg_mgdl=150, meal_slot="lunch", target_mgdl=None)
    response = recommend_bolus(request, settings, iob_u=1.0)

    assert response.upfront_u == 6.0
    assert any("Carbohidratos" in item for item in response.explain)


def test_bolus_low_bg_blocks():
    settings = _settings()
    request = BolusRequestData(carbs_g=50, bg_mgdl=65, meal_slot="lunch", target_mgdl=None)
    response = recommend_bolus(request, settings, iob_u=0)

    assert response.upfront_u == 0.0
    assert any("BG < 70" in item for item in response.explain)
