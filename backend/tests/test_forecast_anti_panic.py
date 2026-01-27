
import pytest
from app.services.forecast_engine import ForecastEngine

class TestAntiPanicGating:
    
    def test_no_linked_meal(self):
        """Should apply no scaling if no linked meal is present"""
        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=30,
            is_linked_meal=False,
            deviation_slope=-2.0,
            predicted_bg=100.0
        )
        assert scale == 1.0
        assert details['applied'] is False

    def test_late_simulation(self):
        """Should apply no scaling if t >= 120 (outside of early meal window)"""
        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=130,
            is_linked_meal=True,
            deviation_slope=-2.0,
            predicted_bg=100.0
        )
        assert scale == 1.0
        assert details['applied'] is False

    def test_moderate_drop_partial_release(self):
        """
        Tests the core PR requirement:
        - Linked meal active
        - Moderate drop (-2.0 slope) which is between -1.0 and -2.5
        - Should result in partial release (scale > base_scale but < 1.0)
        """
        t = 30
        predicted_bg = 120
        # Expected Slope calc:
        # slope_release = (-1.0 - (-2.0)) / (-1.0 - (-2.5)) = 1 / 1.5 = 0.666...
        # Base scale at 30 min: 0.6 + 0.4 * (30/90) = 0.6 + 0.133 = 0.733
        # Final = 0.733 + (1 - 0.733) * 0.666 = 0.733 + 0.267 * 0.666 = 0.733 + 0.178 = 0.911
        
        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=t,
            is_linked_meal=True,
            deviation_slope=-2.0,
            predicted_bg=predicted_bg
        )
        
        assert details['applied'] is True
        assert 0.73 < details['anti_panic_base_scale'] < 0.74
        assert 0.90 < scale < 0.92
        assert scale < 1.0 # Still some dampening
        assert 0.66 < details['release_components']['slope_release'] < 0.67

    def test_threshold_crossing_smoothness(self):
        """
        Tests -2.4 vs -2.6 to ensure no massive jump.
        Previous binary logic: -2.4 -> damp active (0.73), -2.6 -> damp off (1.0). Jump 0.27.
        New logic:
        -2.4 release = 1.4/1.5 = 0.933. Final = 0.733 + 0.267 * 0.933 = 0.98
        -2.6 release = 1.0. Final = 1.0.
        Jump = 0.02. Much smoother.
        """
        t = 30
        
        scale_24, _ = ForecastEngine._compute_anti_panic_scale(
            t_min=t, is_linked_meal=True, deviation_slope=-2.4, predicted_bg=120
        )
        scale_26, _ = ForecastEngine._compute_anti_panic_scale(
            t_min=t, is_linked_meal=True, deviation_slope=-2.6, predicted_bg=120
        )
        
        assert scale_26 == 1.0
        assert scale_24 > 0.95
        assert abs(scale_26 - scale_24) < 0.05

    def test_hypo_risk_release(self):
        """
        Tests release when predicted BG is low (< 80).
        """
        # Slope is 0 (no momentum reason to release)
        # Pred BG = 79 (< 80). Full release.
        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=30, is_linked_meal=True, deviation_slope=0.0, predicted_bg=79.0
        )
        assert scale == 1.0
        assert details['release_components']['hypo_release'] == 1.0
        
        # Pred BG = 85 (Midway 90-80). Release 0.5.
        scale_mid, details_mid = ForecastEngine._compute_anti_panic_scale(
            t_min=30, is_linked_meal=True, deviation_slope=0.0, predicted_bg=85.0
        )
        assert details_mid['release_components']['hypo_release'] == 0.5
        assert scale_mid > details_mid['anti_panic_base_scale']

    def test_combined_release(self):
        """Should take the maximum of slope vs hypo release"""
        # Modest slope (-1.5) -> Release 0.5/1.5 = 0.33
        # Strong hypo risk (82) -> Release 0.8
        # Should use 0.8
        
        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=30, is_linked_meal=True, deviation_slope=-1.5, predicted_bg=82.0
        )
        
        slope_r = details['release_components']['slope_release'] # ~0.33
        hypo_r = details['release_components']['hypo_release'] # 0.8
        
        assert hypo_r > slope_r
        # Result should track hypo_r
        expected = details['anti_panic_base_scale'] + (1 - details['anti_panic_base_scale']) * hypo_r
        assert abs(scale - expected) < 0.001

if __name__ == "__main__":
    pytest.main([__file__])
