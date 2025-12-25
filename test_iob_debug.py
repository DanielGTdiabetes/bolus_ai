
import math
from datetime import datetime, timedelta

# Mocking the InsulinCurves logic
class InsulinCurves:
    @staticmethod
    def _walsh_tau(peak_min, duration_min):
        if duration_min <= 0: return 0
        denom = 1 - 2 * peak_min / duration_min
        if denom == 0: return 0
        return peak_min * (1 - peak_min / duration_min) / denom

    @staticmethod
    def _walsh_F(t, duration, tau):
        if tau == 0: return 0
        term = (tau/duration) - 1 + (t/duration)
        return tau * math.exp(-t/tau) * term

    @staticmethod
    def exponential_iob(t_min: float, peak_min: float, duration_min: float) -> float:
        if t_min <= 0: return 1.0
        if t_min >= duration_min: return 0.0
        
        tau = InsulinCurves._walsh_tau(peak_min, duration_min)
        if tau <= 0:
            return max(0.0, 1.0 - t_min / duration_min)
            
        F0 = InsulinCurves._walsh_F(0, duration_min, tau)
        FD = InsulinCurves._walsh_F(duration_min, duration_min, tau)
        Ft = InsulinCurves._walsh_F(t_min, duration_min, tau)
        
        denom = FD - F0
        if denom == 0: return 0.0
        return (FD - Ft) / denom

# Test Curve Decay
print("--- Curve Decay Test (DIA=4h, Peak=75m) ---")
for t in [0, 60, 120, 180, 239, 241]:
    iob_frac = InsulinCurves.exponential_iob(t, 75, 240)
    print(f"Time {t}min: {iob_frac:.4f}")

# Test Deduplication logic
print("\n--- Deduplication Test ---")

def _safe_parse(ts_val):
    return datetime.fromisoformat(str(ts_val))

def _is_duplicate(candidate: dict, existing_list: list[dict]) -> bool:
    c_ts = _safe_parse(candidate["ts"])
    c_units = float(candidate["units"])
    
    for ex in existing_list:
        ex_ts = _safe_parse(ex["ts"])
        ex_units = float(ex["units"])
        
        # Check units (exact or very close)
        if abs(c_units - ex_units) > 0.01:
            print(f"  Rejecting match {ex['ts']} due to units {ex_units} vs {c_units}")
            continue
            
        # Check time (within tolerance)
        diff_seconds = abs((c_ts - ex_ts).total_seconds())
        print(f"  Checking match {ex['ts']}: diff {diff_seconds}s")
        if diff_seconds < 120: 
            return True
    return False

# Scenario: NS has a bolus, Local has a bolus slightly offset
now = datetime.now()
local_list = [{"ts": now.isoformat(), "units": 4.0}]
ns_candidate = {"ts": (now + timedelta(minutes=2, seconds=10)).isoformat(), "units": 4.0}

print(f"Local: {local_list[0]}")
print(f"NS Candidate: {ns_candidate}")
is_dup = _is_duplicate(ns_candidate, local_list)
print(f"Is Duplicate (Window 120s): {is_dup}")

# Test with 5 mins window
print("\n--- Should match with 5 min window? ---")
if abs((_safe_parse(ns_candidate["ts"]) - _safe_parse(local_list[0]["ts"])).total_seconds()) < 300:
    print("Yes, fits in 300s")
