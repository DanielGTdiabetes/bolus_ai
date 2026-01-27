
import pytest
from app.models.forecast import ForecastSimulateRequest, SimulationParams, ForecastEvents, ForecastBasalInjection
from app.services.forecast_engine import ForecastEngine

def test_neutral_basal_mode():
    params = SimulationParams(
        isf=50, icr=10, dia_minutes=360, carb_absorption_minutes=180,
        basal_daily_units=24.0, # Reference 1.0 U/h
        basal_drift_handling="neutral"
    )
    # Active Basal: 12.0 U / 24h = 0.5 U/h.
    # Deficit = 0.5 - 1.0 = -0.5 U/h.
    # Standard drift would be huge UP.
    
    events = ForecastEvents(
        basal_injections=[
            ForecastBasalInjection(time_offset_min=-60, units=12.0, duration_minutes=1440, type="glargine") 
        ]
    )
    req = ForecastSimulateRequest(start_bg=100, params=params, events=events, horizon_minutes=60)
    
    res = ForecastEngine.calculate_forecast(req)
    
    # Check components
    # We inspect the components list.
    basal_impacts = [c.basal_impact for c in res.components]
    
    # Floating point safety check
    total_impact = sum(basal_impacts)
    assert abs(total_impact) < 0.1, f"Basal impact should be 0 in neutral mode, got {total_impact}"
    
    # Check BG series (Start 100). Should be flat 100.
    final_bg = res.series[-1].bg
    assert abs(final_bg - 100.0) < 1.0, f"Expected 100, got {final_bg}"

def test_standard_basal_drift():
    params = SimulationParams(
        isf=50, icr=10, dia_minutes=360, carb_absorption_minutes=180,
        basal_daily_units=24.0, # Ref 1.0 U/h
        basal_drift_handling="standard"
    )
    # Active 0.5 U/h. Deficit -0.5 U/h.
    # Impact = -1 * (-0.5) * ISF(50) = +25 mg/dL per hour.
    
    events = ForecastEvents(
        basal_injections=[
            ForecastBasalInjection(time_offset_min=-60, units=12.0, duration_minutes=1440, type="glargine") 
        ]
    )
    req = ForecastSimulateRequest(start_bg=100, params=params, events=events, horizon_minutes=60)
    res = ForecastEngine.calculate_forecast(req)
    
    final_bg = res.series[-1].bg
    print(f"Standard Final BG: {final_bg}")
    assert final_bg > 110.0, "Standard mode should drift up significantly"
    
if __name__ == "__main__":
    # Allow running directly
    try:
        test_neutral_basal_mode()
        print("test_neutral_basal_mode PASSED")
        test_standard_basal_drift()
        print("test_standard_basal_drift PASSED")
    except AssertionError as e:
        print(f"FAILED: {e}")
