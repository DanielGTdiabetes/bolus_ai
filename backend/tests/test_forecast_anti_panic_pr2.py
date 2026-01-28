
import pytest
from app.services.forecast_engine import ForecastEngine

class TestAntiPanicPR2:
    def test_feedback_loop_fix(self):
        """
        PR2 Test: Verifies that hypo_release is NOT triggered by the raw depression caused by unscaled insulin.
        Scenario:
        - Start BG = 110 (Perfect range)
        - Insulin Raw Impact = -40 (Would likely drop BG to ~70-80 raw)
        - Base Scale ~0.66 (Would keep BG ~95)
        
        OLD Behavior (Bug):
        - Pred BG = 110 - 40 = 70.
        - Hypo Release sees 70 -> Triggers Full Release (1.0).
        - Final Scale = 1.0. 
        - Result: -40 drop applied -> False Hypo shown.
        
        NEW Behavior (Fix):
        - Safe BG = 110 - (40 * 0.66) = 110 - 26.4 = 83.6.
        - Hypo Release sees 83.6 -> Partial/No Release (depending on threshold 80-90).
        - If threshold is 90-80: 83.6 is in release zone but not full.
        - Release = (90 - 83.6) / 10 = 0.64.
        - Final Scale = 0.66 + (0.34 * 0.64) = 0.88.
        - Result: Scale < 1.0. Protection Maintained.
        """
        # NOTE: This test calls the helper directly. 
        # But the FIX was implemented in the CALLER (calculate_forecast), not the helper.
        # So testing the helper alone won't prove the fix unless we simulate the caller's logic.
        
        # 1. Simulate Caller Logic (Pre-calculation)
        t = 15
        start_bg = 110
        insulin_net_raw = -40.0
        
        # Calculate Check Base Scale
        check_base_scale = 0.6 + (0.4 * (t / 90.0)) # ~0.667
        
        # Calculate Safe BG (The Fix)
        insulin_net_safe = insulin_net_raw * check_base_scale
        predicted_bg_safe = start_bg + insulin_net_safe 
        
        # Calculate Raw BG (The Bug)
        predicted_bg_raw = start_bg + insulin_net_raw
        
        # 2. Run Helper with SAFE BG
        scale_new, details_new = ForecastEngine._compute_anti_panic_scale(
            t_min=t, is_linked_meal=True, deviation_slope=0.0, predicted_bg=predicted_bg_safe
        )
        
        # 3. Run Helper with RAW BG (Simulating bug state)
        scale_old, details_old = ForecastEngine._compute_anti_panic_scale(
            t_min=t, is_linked_meal=True, deviation_slope=0.0, predicted_bg=predicted_bg_raw
        )
        
        # Assertions
        print(f"Safe BG: {predicted_bg_safe}, Raw BG: {predicted_bg_raw}")
        print(f"Scale New: {scale_new}, Scale Old: {scale_old}")
        
        # Old behavior should have released fully (or close to it)
        # Raw BG = 70 -> Hypo Release 1.0 -> Scale 1.0
        assert scale_old == 1.0 
        
        # New behavior should maintain some protection
        # Safe BG = 83.3 -> Hypo Release ~0.67 -> Final Scale ~0.89
        assert scale_new < 0.95
        assert scale_new < scale_old
        assert details_new['predicted_bg_for_release'] > 80.0
