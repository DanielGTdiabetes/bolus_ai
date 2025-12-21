import sys
import os

# Adjust path to include backend
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)

from app.models.forecast import ForecastSimulateRequest, SimulationParams, ForecastEvents, ForecastEventCarbs, ForecastEventBolus
from app.services.forecast_engine import ForecastEngine

sys.stdout.reconfigure(encoding='utf-8')

def run_simulation(absorption_minutes):
    print(f"\n--- Simulating with Absorption: {absorption_minutes} minutes ---")
    
    # 1. Setup Parameters (User's Scenario)
    # 9g Carbs, 3.5U Insulin
    # ICR 2.5, ISF 30
    # Start BG 120
    
    sim_params = SimulationParams(
        isf=30.0,
        icr=2.5,
        dia_minutes=240, # 4 hours
        carb_absorption_minutes=absorption_minutes,
        insulin_peak_minutes=75
    )
    
    events = ForecastEvents(
        boluses=[ForecastEventBolus(time_offset_min=0, units=3.5)],
        carbs=[ForecastEventCarbs(time_offset_min=0, grams=9.0, icr=2.5, absorption_minutes=absorption_minutes)]
    )
    
    req = ForecastSimulateRequest(
        start_bg=130.0,
        params=sim_params,
        events=events,
        horizon_minutes=360 # 6 hours
    )
    
    # 2. Run Engine
    response = ForecastEngine.calculate_forecast(req)
    
    # 3. Analyze Results
    min_bg = response.summary.min_bg
    min_time = response.summary.time_to_min
    ending_bg = response.summary.ending_bg
    
    print(f"Min BG: {min_bg} mg/dL at {min_time} min")
    print(f"Ending BG: {ending_bg} mg/dL")
    
    # Visual check of the dip
    # Let's print points every 30 mins
    print("Snapshot first 60m (every 10m):")
    for p, c in zip(response.series, response.components):
        if p.t_min <= 60 and p.t_min % 10 == 0:
            print(f"  T+{p.t_min}m: BG {p.bg} | Ins {c.insulin_impact} | Carb {c.carb_impact}")
            
    return min_bg

def check_insulin_curve():
    from app.services.math.curves import InsulinCurves
    peak = 75
    dur = 240
    total_area = 0.0
    dt = 1.0
    for t in range(0, dur + 1):
        rate = InsulinCurves.exponential_activity(t, peak, dur)
        total_area += rate * dt
    print(f"\n--- INSULIN CURVE CHECK (Peak {peak}, Dur {dur}) ---")
    print(f"Total Area (should be ~1.0): {total_area}")
    
def main():
    print("=== FORECAST SIMULATION TEST ===")
    check_insulin_curve()
    
    print("Scenario: 9g Carbs + 3.5U Insulin (ICR 2.5). Starting BG 130.")
    print("Hypothesis: 100min absorption causes low. 180min prevents it.")
    
    # Case A: Old default for snacks (100 min)
    min_a = run_simulation(100)
    
    # Case B: New default for meals/user setting (180 min)
    min_b = run_simulation(180)
    
    print("\n=== SUMMARY ===")
    print(f"Case A (100 min): Min {min_a}")
    print(f"Case B (180 min): Min {min_b}")
    
    if min_a < 70 and min_b > 70:
        print("\n✅ SUCCESS: Granular absorption setting (180 min) fixes the false hypoglycemia prediction!")
    elif min_a < 70 and min_b < 70:
        print("\n⚠️  WARNING: Still low even with 180 min. Maybe ICR 2.5 is too aggressive properly?")
    else:
        print("\nℹ️  INFO: Behavior difference observed.")

if __name__ == "__main__":
    main()
