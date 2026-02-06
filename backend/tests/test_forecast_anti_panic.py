
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
        """Should apply no scaling if t >= full_release + 30 (outside of early meal window)"""
        # For 'med' profile: full_release=90, so t >= 120 should be ungated
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
        Tests partial release with moderate drop.
        Profile 'med': phase1_end=30, full_release=90.
        At t=30: just entering phase 2 -> base_scale = 0.6
        slope_release = (-1.0 - (-2.0)) / (-1.0 - (-2.5)) = 1/1.5 = 0.666
        Final = 0.6 + (1 - 0.6) * 0.666 = 0.6 + 0.267 = 0.867
        """
        t = 30
        predicted_bg = 120

        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=t,
            is_linked_meal=True,
            deviation_slope=-2.0,
            predicted_bg=predicted_bg
        )

        assert details['applied'] is True
        assert 0.59 < details['anti_panic_base_scale'] < 0.61
        assert 0.85 < scale < 0.88
        assert scale < 1.0  # Still some dampening
        assert 0.66 < details['release_components']['slope_release'] < 0.67

    def test_threshold_crossing_smoothness(self):
        """
        Tests -2.4 vs -2.6 to ensure no massive jump.
        At t=30, med profile: base_scale=0.6
        -2.4: release = 1.4/1.5 = 0.933. Final = 0.6 + 0.4 * 0.933 = 0.973
        -2.6: release = 1.0. Final = 1.0.
        Jump = 0.027. Smooth.
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
        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=30, is_linked_meal=True, deviation_slope=-1.5, predicted_bg=82.0
        )

        slope_r = details['release_components']['slope_release']
        hypo_r = details['release_components']['hypo_release']

        assert hypo_r > slope_r
        # Result should track hypo_r
        expected = details['anti_panic_base_scale'] + (1 - details['anti_panic_base_scale']) * hypo_r
        assert abs(scale - expected) < 0.001


class TestAntiPanicProfileAware:
    """Tests for profile-aware anti-panic dampening (fast/med/slow)."""

    def test_fast_profile_shorter_dampening(self):
        """Fast carbs: phase1=15min, full_release=45min. At t=50 should be ungated."""
        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=50,
            is_linked_meal=True,
            deviation_slope=-1.0,
            predicted_bg=120.0,
            carb_profile="fast",
        )
        # t=50 > full_release(45), so base_scale should be 1.0
        assert scale == 1.0

    def test_fast_profile_active_early(self):
        """Fast carbs: at t=10 should be in phase 1 (active dampening)."""
        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=10,
            is_linked_meal=True,
            deviation_slope=0.0,
            predicted_bg=150.0,
            carb_profile="fast",
        )
        assert details['applied'] is True
        # phase1_end=15, t=10: base_scale = 0.35 + 0.25*(10/15) = 0.517
        assert 0.50 < details['anti_panic_base_scale'] < 0.53

    def test_slow_profile_longer_dampening(self):
        """Slow carbs: phase1=45min, full_release=120min. At t=100 should still be damped."""
        scale, details = ForecastEngine._compute_anti_panic_scale(
            t_min=100,
            is_linked_meal=True,
            deviation_slope=0.0,
            predicted_bg=150.0,
            carb_profile="slow",
        )
        assert details['applied'] is True
        # phase2: 0.6 + 0.4 * ((100-45)/(120-45)) = 0.6 + 0.4 * (55/75) = 0.893
        assert 0.88 < details['anti_panic_base_scale'] < 0.90

    def test_slow_vs_fast_at_same_time(self):
        """At t=30, slow profile should be more dampened than fast profile."""
        scale_fast, _ = ForecastEngine._compute_anti_panic_scale(
            t_min=30, is_linked_meal=True, deviation_slope=0.0,
            predicted_bg=150.0, carb_profile="fast",
        )
        scale_slow, _ = ForecastEngine._compute_anti_panic_scale(
            t_min=30, is_linked_meal=True, deviation_slope=0.0,
            predicted_bg=150.0, carb_profile="slow",
        )
        # Fast at t=30: past full_release(45)? No, but past phase1_end(15).
        # phase2: 0.6 + 0.4 * (15/30) = 0.8
        # Slow at t=30: still in phase1 (phase1_end=45)
        # 0.35 + 0.25 * (30/45) = 0.517
        assert scale_fast > scale_slow

    def test_med_profile_is_default(self):
        """Calling without carb_profile should behave like 'med'."""
        scale_default, details_default = ForecastEngine._compute_anti_panic_scale(
            t_min=30, is_linked_meal=True, deviation_slope=-1.5, predicted_bg=120.0,
        )
        scale_med, details_med = ForecastEngine._compute_anti_panic_scale(
            t_min=30, is_linked_meal=True, deviation_slope=-1.5, predicted_bg=120.0,
            carb_profile="med",
        )
        assert abs(scale_default - scale_med) < 0.001


if __name__ == "__main__":
    pytest.main([__file__])
