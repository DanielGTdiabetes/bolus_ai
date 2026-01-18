from datetime import datetime, timezone
import pytest
from app.models.bolus_v2 import BolusRequestV2, GlucoseUsed
from app.models.settings import UserSettings
from app.services.bolus_engine import calculate_bolus_v2

def test_engine_basic_meal():
    # 1) carbs 10g, CR 10 g/U => meal 1.0U
    settings = UserSettings()
    settings.cr.lunch = 10.0
    settings.cf.lunch = 50.0  # ISF
    settings.targets.mid = 100
    settings.iob.dia_hours = 4

    req = BolusRequestV2(carbs_g=10.0, meal_slot="lunch")
    glucose = GlucoseUsed(mgdl=100.0, source="manual") # on target
    
    res = calculate_bolus_v2(req, settings, iob_u=0.0, glucose_info=glucose)
    
    assert res.total_u == 1.0
    assert res.kind == "normal"
    assert "A) Comida: 10.0g / 10.0 = 1.00 U" in res.explain[0]

def test_engine_correction_only():
    # 2) bg 220, target 120, ISF 50 => corr 2.0U
    settings = UserSettings()
    settings.cr.lunch = 10.0
    settings.cf.lunch = 50.0
    
    req = BolusRequestV2(carbs_g=0.0, target_mgdl=120.0, bg_mgdl=220.0, meal_slot="lunch")
    glucose = GlucoseUsed(mgdl=220.0, source="manual")
    
    res = calculate_bolus_v2(req, settings, iob_u=0.0, glucose_info=glucose)
    
    # (220 - 120) / 50 = 2.0 U
    assert res.total_u == 2.0
    assert "B) Corrección: (220 - 120) / 50 = 2.00 U" in res.explain[1]

def test_engine_iob_subtraction():
    # 3) iob 1.0U => total = (meal+corr)-iob
    # Meal 10g/10 = 1U. Corr 0. IOB 0.5. Total 0.5
    settings = UserSettings()
    settings.cr.lunch = 10.0
    
    req = BolusRequestV2(carbs_g=10.0, bg_mgdl=100.0, target_mgdl=100.0)
    glucose = GlucoseUsed(mgdl=100.0, source="manual")
    
    res = calculate_bolus_v2(req, settings, iob_u=0.5, glucose_info=glucose)
    assert res.total_u == 0.5
    assert "C) IOB: 0.50 U activos." in res.explain[2]

def test_engine_exercise_reduction():
    # 4) exercise 60min moderate => reduce ~30%
    settings = UserSettings()
    settings.cr.lunch = 10.0
    
    req = BolusRequestV2(carbs_g=10.0, bg_mgdl=100.0) # 1.0 U base
    req.exercise.planned = True
    req.exercise.minutes = 60
    req.exercise.intensity = "moderate" # Table says 0.30 reduction
    
    glucose = GlucoseUsed(mgdl=100.0, source="manual")
    
    res = calculate_bolus_v2(req, settings, iob_u=0.0, glucose_info=glucose)
    
    # 1.0 * (1 - 0.30) = 0.70, rounded to 0.5
    assert res.total_u == 0.5
    # Check explain contains percentage
    found = any("-30%" in x for x in res.explain)
    assert found

def test_engine_extended_bolus():
    # 5) extended upfront 0.6 duration 180 => split correcto
    settings = UserSettings()
    settings.cr.lunch = 10.0
    settings.round_step_u = 0.05
    
    # Base 2.0 U (20g carbs)
    req = BolusRequestV2(carbs_g=20.0, bg_mgdl=100.0)
    req.slow_meal.enabled = True
    req.slow_meal.upfront_pct = 0.6
    req.slow_meal.duration_min = 180
    
    glucose = GlucoseUsed(mgdl=100.0, source="manual")
    
    res = calculate_bolus_v2(req, settings, iob_u=0.0, glucose_info=glucose)
    
    # Total 2.0
    # Upfront: 2.0 * 0.6 = 1.2
    # Later: 2.0 * 0.4 = 0.8
    assert res.total_u == 2.0
    assert res.kind == "normal"
    assert res.upfront_u == 2.0
    assert res.later_u == 0.0
    assert res.duration_min == 0
