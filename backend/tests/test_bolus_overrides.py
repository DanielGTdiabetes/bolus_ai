from app.models.bolus_v2 import BolusRequestV2, GlucoseUsed
from app.models.settings import UserSettings
from app.services.bolus_engine import calculate_bolus_v2

def test_engine_explicit_overrides():
    settings = UserSettings()
    settings.cr.lunch = 10.0
    settings.cf.lunch = 30.0
    
    # CASE 1: No overrides -> uses settings
    req = BolusRequestV2(carbs_g=20.0, meal_slot="lunch")
    glucose = GlucoseUsed(mgdl=100.0, source="manual")
    res = calculate_bolus_v2(req, settings, iob_u=0.0, glucose_info=glucose)
    assert res.total_u == 2.0  # 20/10 = 2

    # CASE 2: Override CR
    req2 = BolusRequestV2(carbs_g=20.0, meal_slot="lunch", cr_g_per_u=20.0)
    res2 = calculate_bolus_v2(req2, settings, iob_u=0.0, glucose_info=glucose)
    assert res2.total_u == 1.0  # 20/20 = 1

    # CASE 3: Override ISF and CR
    # Settings: ISF 30. Override ISF 100.
    # BG=200, Target=100. Diff=100.
    # Standard: 100/30 = 3.33
    # Override: 100/100 = 1.0
    req3 = BolusRequestV2(
        carbs_g=0.0, 
        meal_slot="lunch", 
        bg_mgdl=200.0, 
        target_mgdl=100.0,
        isf_mgdl_per_u=100.0 
    )
    glucose3 = GlucoseUsed(mgdl=200.0, source="manual")
    res3 = calculate_bolus_v2(req3, settings, iob_u=0.0, glucose_info=glucose3)
    assert res3.total_u == 1.0
