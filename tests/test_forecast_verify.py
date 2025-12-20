import pytest
import math
from app.services.forecast_engine import ForecastEngine
from app.models.forecast import (
    ForecastSimulateRequest, SimulationParams, ForecastEvents, 
    ForecastEventBolus, ForecastEventCarbs, ForecastBasalInjection, MomentumConfig
)
from app.services.math.curves import InsulinCurves, CarbCurves

# Mock Params
PARAMS = SimulationParams(
    isf=30.0, # 1U drops 30 mg/dL
    icr=10.0, # 10g raises 30 mg/dL (10g needs 1U)
    dia_minutes=360,
    carb_absorption_minutes=180
)

def test_curves_sanity():
    # Insulin Peak at 75, Duration 360
    # At t=0 should be 0
    assert InsulinCurves.exponential_activity(0, 75, 360) == 0
    # At t=75 should be roughly max
    peak_val = InsulinCurves.exponential_activity(75, 75, 360)
    assert peak_val > 0
    # At t=360 should be 0
    assert InsulinCurves.exponential_activity(360, 75, 360) < 0.001

def test_forecast_bolus_only():
    req = ForecastSimulateRequest(
        start_bg=200,
        horizon_minutes=180,
        step_minutes=5,
        params=PARAMS,
        events=ForecastEvents(
            boluses=[ForecastEventBolus(time_offset_min=0, units=2.0)]
        )
    )
    res = ForecastEngine.calculate_forecast(req)
    
    # 2U * 30 ISF = 60 mg/dL drop total
    # At 3 hours (180 min), roughly 50-70% should be absorbed.
    # So BG should be around 200 - (60 * 0.5) = 170 ish.
    
    end_bg = res.series[-1].bg
    assert end_bg < 200, "Bolus should lower BG"
    assert end_bg > 140, "Should not drop full amount instantly"
    
def test_forecast_carbs_only():
    req = ForecastSimulateRequest(
        start_bg=100,
        horizon_minutes=180,
        step_minutes=5,
        params=PARAMS,
        events=ForecastEvents(
            carbs=[ForecastEventCarbs(time_offset_min=0, grams=10.0)]
        )
    )
    res = ForecastEngine.calculate_forecast(req)
    
    # 10g Carbs. ICR=10 => Needs 1U.
    # 1U covers 30mg/dL. So 10g raises 30mg/dL.
    # Total rise should be 30.
    # At 180 min (3h), Carb Duration is 180, so mostly absorbed.
    
    end_bg = res.series[-1].bg
    assert end_bg > 100, "Carbs should raise BG"
    # Allow some tolerance for curve shape integration
    assert 120 <= end_bg <= 140, f"Expected ~130, got {end_bg}"

def test_forecast_momentum_cap():
    # Provide data with massive slope
    recent = [
        {'minutes_ago': 0, 'value': 200},
        {'minutes_ago': 5, 'value': 100}, # dropped 100 in 5 min => -20 mg/dL/min
    ]
    # Max Cap is +/- 3 usually (in code I put 3.0)
    
    req = ForecastSimulateRequest(
        start_bg=200,
        params=PARAMS,
        momentum=MomentumConfig(enabled=True, lookback_points=3),
        recent_bg_series=recent
    )
    # We need 3 points for momentum logic in code
    req.recent_bg_series.append({'minutes_ago': 10, 'value': 0}) 
    
    # Actually code check: "if len(points) < lookback_points (3): return 0"
    
    res = ForecastEngine.calculate_forecast(req)
    # Should have warnings
    assert any("capped" in w.lower() for w in res.warnings)

if __name__ == "__main__":
    # Manual run if pytest not available
    try:
        test_curves_sanity()
        print("Curves OK")
        test_forecast_bolus_only()
        print("Bolus OK")
        test_forecast_carbs_only()
        print("Carbs OK")
        test_forecast_momentum_cap()
        print("Momentum OK")
        print("ALL TESTS PASSED")
    except Exception as e:
        print(f"TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
