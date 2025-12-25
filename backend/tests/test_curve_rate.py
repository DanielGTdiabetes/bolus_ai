
import asyncio
import sys
import os

# Setup path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(backend_dir)

from app.services.math.curves import InsulinCurves

def test_curves_rate():
    print("--- Testing Curve RATE ---")
    
    # Fiasp: Peak 55, DIA 300
    peak = 55
    dia = 300
    
    times = [0, 30, 60, 120]
    for t in times:
        rate = InsulinCurves.get_activity(t, dia, peak, "fiasp")
        # Rate is fraction of dose per minute.
        # Sum of rate * dt over DIA should be 1.0.
        print(f"T={t}, Rate={rate:.6f}")
        
    print("-- Summation Check --")
    total_area = 0.0
    dt = 1.0
    for t in range(0, dia+1):
        rate = InsulinCurves.get_activity(t, dia, peak, "fiasp")
        total_area += rate * dt
        
    print(f"Total Area (Integral): {total_area:.4f}")
    if total_area > 1.1 or total_area < 0.9:
        print("FAIL: Area is not 1.0")
    else:
        print("PASS: Area is approx 1.0")

if __name__ == "__main__":
    test_curves_rate()
