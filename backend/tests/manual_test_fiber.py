import logging
import asyncio
from app.services.math.curves import CarbCurves

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_fiber_impact():
    print("\n--- Test 1: High Fiber vs No Fiber ---")
    
    carbs = 60.0 # 60g carbs
    
    # 1. Standard (No Fiber)
    params_std = CarbCurves.get_biexponential_params(carbs, fiber_g=0, fat_g=0, protein_g=0)
    print(f"Standard Params (0g fiber): f={params_std['f']:.2f}, t_max_l={params_std['t_max_l']:.1f}")
    
    # 2. High Fiber (Lentils - 15g fiber)
    # Logic: fiber_ratio = 15/60 = 0.25. f reduction = 0.25. f = 0.7 - 0.25 = 0.45.
    params_fiber = CarbCurves.get_biexponential_params(carbs, fiber_g=15, fat_g=0, protein_g=0)
    print(f"High Fiber Params (15g):    f={params_fiber['f']:.2f}, t_max_l={params_fiber['t_max_l']:.1f}")

    # Check Impact at 60 minutes
    t = 60
    abs_std = CarbCurves.biexponential_absorption(t, params_std)
    abs_fiber = CarbCurves.biexponential_absorption(t, params_fiber)
    
    print(f"\nAbsorption Rate at t=60min:")
    print(f"Standard: {abs_std:.4f}")
    print(f"Fiber:    {abs_fiber:.4f}")
    print(f"Difference: {((abs_fiber - abs_std)/abs_std)*100:.1f}% slower/faster")
    
    if params_fiber['f'] < params_std['f']:
        print("PASS: Fast fraction reduced by fiber.")
    else:
        print("FAIL: Fiber did not reduce fast fraction.")
        
    print("\n--- Test 2: Threshold < 5g (Validation of logic update needed) ---")
    # Current logic does NOT have the <5g threshold yet. We will verify the logic update later.
    # This test confirms the CURRENT implementation responds to ANY fiber.
    params_tiny = CarbCurves.get_biexponential_params(carbs, fiber_g=2, fat_g=0, protein_g=0)
    print(f"Tiny Fiber (2g): f={params_tiny['f']:.2f} (Base is 0.7)")
    
    if params_tiny['f'] < 0.7:
        print("INFO: Currently logic affects even small fiber amounts.")
    else:
         print("INFO: Logic already ignores small amounts (Checked by Ratio?)")

if __name__ == "__main__":
    asyncio.run(test_fiber_impact())
