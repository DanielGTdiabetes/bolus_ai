
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(backend_dir)

from app.services.forecast_engine import ForecastEngine
from app.models.forecast import ForecastSimulateRequest, ForecastEventBolus, SimulationParams, ForecastEvents

def test_forecast_issue():
    print("--- REPRODUCING FORECAST LOW ---")
    
    # 1. Setup Request that mirrors the user scenario
    # Current BG: 232
    # Bolus Proposed: 2.0 U (Now)
    # History IOB:
    # - 1.5 U @ -72 min
    # - 0.5 U @ -152 min (2h32m)
    # - 2.5 U @ -156 min (2h36m)
    # - 2.5 U @ -203 min (3h23m)
    
    # ISF: 50
    # Model: Fiasp (Peak 55, DIA ? User said "Fiasp" in screenshot). 
    # Let's assume DIA=5h (300 min) or 4h (240 min). 
    # Standard Fiasp is 5h usually in Loop settings but curves decay fast.
    
    params = SimulationParams(
        isf=50, 
        icr=10, 
        dia_minutes=300, 
        carb_absorption_minutes=180,
        insulin_peak_minutes=55,
        insulin_model="fiasp"
    )
    
    events = ForecastEvents()
    # Proposed
    events.boluses.append(ForecastEventBolus(time_offset_min=0, units=2.0))
    
    # History
    events.boluses.append(ForecastEventBolus(time_offset_min=-72, units=1.5))
    events.boluses.append(ForecastEventBolus(time_offset_min=-152, units=0.5))
    events.boluses.append(ForecastEventBolus(time_offset_min=-156, units=2.5))
    events.boluses.append(ForecastEventBolus(time_offset_min=-203, units=2.5))
    
    req = ForecastSimulateRequest(
        start_bg=232,
        params=params,
        events=events,
        momentum=None # Disable momentum to isolate math
    )
    
    print(f"Start BG: {req.start_bg}")
    print(f"Boluses: {len(events.boluses)}")
    
    # Run
    res = ForecastEngine.calculate_forecast(req)
    
    print(f"Summary Min: {res.summary.min_bg}")
    print(f"Summary End: {res.summary.ending_bg}")
    
    if res.summary.min_bg <= 20:
        print("REPRODUCED: Min BG is <= 20.")
    else:
        print(f"NOT REPRODUCED: Min BG is {res.summary.min_bg}")
        
    # Analyze where 20 comes from
    # Logic: Start - (TotalInsulin * ISF) + (Carbs...)
    # Total Insulin in list: 2 + 1.5 + 0.5 + 2.5 + 2.5 = 9.0 U ?
    # Wait, history boluses are FULL units.
    # The math in forecast engine subtracts effect from t=0 onwards.
    # So it calculates:
    # Effect of 1.5U taken 72m ago -> How much activity remains from t=0 to t=DIA?
    # It accumulates delta G.
    
    # Let's verify standard math.
    # 2.0 U (Now) -> Full effect = 2 * 50 = 100 drop.
    # 1.5 U (-72m) -> Remaining effect?
    # Fiasp @ 72m (Peak 55, DIA 300).
    # Approx 60-70% consumed? So 30-40% remaining? ~0.5 U. Drop ~25.
    # 2.5 U (-156m) -> Mostly consumed.
    
    # Total expected drop ~ 100 (New) + ~30 (IOB) = 130.
    # 232 - 130 = 102.
    
    # If 9.0 U were all counted as new: 9 * 50 = 450 drop -> BG negative -> Clamped to 20?
    pass

if __name__ == "__main__":
    test_forecast_issue()
