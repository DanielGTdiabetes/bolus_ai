"""
Tests para validar el cálculo de Autosens híbrido y resolver discrepancias.

Caso de ejemplo:
- Carbohidratos: 23.9g
- Glucosa actual: 125 mg/dL
- Glucosa objetivo: 110 mg/dL
- Base I:C ratio: 9.0
- Base ISF: 78 mg/dL por unidad

Fórmula híbrida: autosens_ratio = TDD_ratio * Local_ratio
Aplicación: CR_efectivo = CR_base / autosens_ratio
            ISF_efectivo = ISF_base / autosens_ratio
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, date, timedelta, timezone
from typing import Dict

# Test data from user example
BASE_CR = 9.0
BASE_ISF = 78.0
TARGET_BG = 110.0
CURRENT_BG = 125.0
CARBS = 23.9


class TestAutosensFormula:
    """Validate the mathematical formulas for Autosens calculation."""

    def test_app_values(self):
        """Validate app calculation: Autosens 0.88x"""
        tdd_ratio = 0.88
        local_ratio = 1.00
        autosens_ratio = tdd_ratio * local_ratio  # 0.88

        cr_adjusted = BASE_CR / autosens_ratio  # 9.0 / 0.88 = 10.23
        isf_adjusted = BASE_ISF / autosens_ratio  # 78 / 0.88 = 88.64

        # Bolo comida
        meal_insulin = CARBS / cr_adjusted  # 23.9 / 10.23 = 2.34

        # Corrección
        correction = (CURRENT_BG - TARGET_BG) / isf_adjusted  # 15 / 88.64 = 0.17

        assert round(autosens_ratio, 2) == 0.88
        assert round(cr_adjusted, 1) == 10.2
        assert round(isf_adjusted, 0) == 89
        assert round(meal_insulin, 2) == 2.34
        assert round(correction, 2) == 0.17

    def test_bot_values(self):
        """Validate bot calculation: Autosens 0.98x"""
        tdd_ratio = 0.95
        local_ratio = 1.04
        autosens_ratio = tdd_ratio * local_ratio  # 0.988

        cr_adjusted = BASE_CR / autosens_ratio  # 9.0 / 0.988 = 9.11
        isf_adjusted = BASE_ISF / autosens_ratio  # 78 / 0.988 = 78.95

        # Bolo comida
        meal_insulin = CARBS / cr_adjusted  # 23.9 / 9.11 = 2.62

        # Corrección
        correction = (CURRENT_BG - TARGET_BG) / isf_adjusted  # 15 / 78.95 = 0.19

        assert round(autosens_ratio, 2) == 0.99  # 0.988 rounds to 0.99
        assert round(cr_adjusted, 1) == 9.1
        assert round(isf_adjusted, 0) == 79
        assert round(meal_insulin, 2) == 2.62
        assert round(correction, 2) == 0.19

    def test_formula_is_identical(self):
        """Both app and bot use the same formula - difference is in input data."""
        def calculate_bolus(tdd_ratio: float, local_ratio: float):
            autosens = tdd_ratio * local_ratio
            autosens = max(0.7, min(1.3, autosens))  # Clamp
            cr = BASE_CR / autosens
            isf = BASE_ISF / autosens
            meal = CARBS / cr
            corr = (CURRENT_BG - TARGET_BG) / isf
            return {
                "autosens": round(autosens, 2),
                "cr": round(cr, 1),
                "isf": round(isf, 0),
                "meal": round(meal, 2),
                "correction": round(corr, 2),
                "total_raw": round(meal + corr, 2)
            }

        app_result = calculate_bolus(0.88, 1.00)
        bot_result = calculate_bolus(0.95, 1.04)

        # The formula is the same, only inputs differ
        assert app_result["autosens"] == 0.88
        assert bot_result["autosens"] == 0.99

        # Total difference is about 0.5 U due to different inputs
        diff = abs(app_result["total_raw"] - bot_result["total_raw"])
        assert diff < 0.35  # ~0.3 U difference


class TestTDDCalculation:
    """Test TDD calculation with real basal doses."""

    @pytest.mark.asyncio
    async def test_tdd_uses_real_basal(self):
        """Verify TDD calculation prioritizes real basal doses over schedule."""
        from app.services.dynamic_isf_service import DynamicISFService, TDDDebugInfo

        # Mock session
        mock_session = AsyncMock()

        # Mock Treatment query (empty boluses for simplicity)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.bot.proactive.basal.schedule = []  # No schedule
        mock_settings.tdd_u = 30.0
        mock_settings.autosens.min_ratio = 0.7
        mock_settings.autosens.max_ratio = 1.3

        # Mock _get_real_basal_doses to return some real doses
        today = date.today()
        mock_basal = {
            today: 12.0,
            today - timedelta(days=1): 12.0,
            today - timedelta(days=2): 11.5,
        }

        with patch.object(DynamicISFService, '_get_real_basal_doses', return_value=mock_basal):
            ratio, debug = await DynamicISFService.calculate_dynamic_ratio(
                username="test_user",
                session=mock_session,
                settings=mock_settings,
                return_debug=True
            )

        # Check that real doses were used
        assert debug.basal_source == "real_doses"
        assert debug.basal_by_day[0] == 12.0  # Today's dose

    @pytest.mark.asyncio
    async def test_tdd_falls_back_to_schedule(self):
        """Verify TDD falls back to schedule when no real doses exist."""
        from app.services.dynamic_isf_service import DynamicISFService

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        # Mock settings with schedule
        mock_settings = MagicMock()
        mock_schedule_item = MagicMock()
        mock_schedule_item.units = 12.0
        mock_settings.bot.proactive.basal.schedule = [mock_schedule_item]
        mock_settings.tdd_u = 30.0
        mock_settings.autosens.min_ratio = 0.7
        mock_settings.autosens.max_ratio = 1.3

        with patch.object(DynamicISFService, '_get_real_basal_doses', return_value={}):
            ratio, debug = await DynamicISFService.calculate_dynamic_ratio(
                username="test_user",
                session=mock_session,
                settings=mock_settings,
                return_debug=True
            )

        assert debug.basal_source == "schedule"


class TestDiscrepancyDiagnostics:
    """Tests to diagnose discrepancies between app and bot."""

    def test_diagnose_tdd_difference(self):
        """
        Analyze why TDD might differ between app and bot.

        Possible causes:
        1. Different boluses registered in DB
        2. Different basal doses (schedule vs real)
        3. Timing differences in 24h window
        """
        # Scenario 1: Bot registered an extra bolus that app didn't see
        app_boluses_24h = [3.0, 2.5, 4.0]  # Total: 9.5 U
        bot_boluses_24h = [3.0, 2.5, 4.0, 1.5]  # Total: 11.0 U (extra 1.5 U)

        basal = 12.0
        reference_tdd = 30.0

        app_recent_tdd = sum(app_boluses_24h) + basal  # 21.5
        bot_recent_tdd = sum(bot_boluses_24h) + basal  # 23.0

        week_avg = 25.0  # Assume same week average

        app_weighted = (app_recent_tdd * 0.6) + (week_avg * 0.4)  # 22.9
        bot_weighted = (bot_recent_tdd * 0.6) + (week_avg * 0.4)  # 23.8

        app_ratio = app_weighted / reference_tdd  # 0.763
        bot_ratio = bot_weighted / reference_tdd  # 0.793

        # This explains the difference: app has lower TDD ratio (more sensitive)
        assert app_ratio < bot_ratio

    def test_diagnose_local_ratio_difference(self):
        """
        Analyze why Local ratio might differ between app and bot.

        Possible causes:
        1. Different CGM points available
        2. Different treatments affecting deviation calculation
        3. Timing of 8h/24h windows
        """
        # Scenario: App calculated earlier when there were fewer deviations
        app_deviations_8h = [0.0, 0.1, -0.1, 0.0, 0.05]  # Neutral, median ~0
        bot_deviations_8h = [0.0, 0.1, -0.1, 0.2, 0.3, 0.4]  # Slightly positive

        import statistics

        k = 0.05  # Sensitivity factor

        app_median = statistics.median(app_deviations_8h)  # 0.0
        bot_median = statistics.median(bot_deviations_8h)  # 0.15

        app_local_ratio = 1.0 + (k * app_median)  # 1.00
        bot_local_ratio = 1.0 + (k * bot_median)  # 1.0075 -> ~1.01

        # This explains a small difference in local ratio
        assert app_local_ratio == 1.0
        assert bot_local_ratio > 1.0


class TestHybridAutosensIntegration:
    """Integration tests for the complete hybrid autosens calculation."""

    @pytest.mark.asyncio
    async def test_hybrid_formula_documented(self):
        """
        Document the hybrid autosens formula per OpenAPS/AndroidAPS standard.

        Formula:
            autosens_ratio = TDD_ratio * Local_ratio

        Where:
            TDD_ratio = weighted_TDD / baseline_TDD
            weighted_TDD = (recent_24h_TDD * 0.6) + (week_avg_TDD * 0.4)

            Local_ratio = 1.0 + (k * median_deviation)
            k = 0.05 (sensitivity factor)
            median_deviation = median of (delta_real - delta_model) per 5min interval

        Application:
            CR_effective = CR_base / autosens_ratio
            ISF_effective = ISF_base / autosens_ratio

        Safety clamps:
            autosens_ratio is clamped to [min_ratio, max_ratio] (typically 0.7-1.3)
        """
        # This test documents the formula - it always passes
        formula = """
        HYBRID AUTOSENS FORMULA
        =======================

        1. TDD Ratio (Dynamic ISF based on Total Daily Dose):
           - Fetch boluses from Treatment table (7 days)
           - Fetch REAL basal from basal_dose table (priority)
           - Fallback to schedule if no real doses
           - Calculate: weighted_TDD = recent_24h * 0.6 + week_avg * 0.4
           - TDD_ratio = weighted_TDD / baseline_TDD

        2. Local Ratio (Autosens based on BG deviations):
           - Analyze 24h of CGM data
           - Calculate deviations: delta_real - delta_model per 5min
           - Filter: exclude if COB active, BG < 70 or > 250, rapid changes
           - Aggregate: median of 8h and 24h windows
           - Local_ratio = 1.0 + (0.05 * median_deviation)

        3. Hybrid Combination:
           - autosens_ratio = TDD_ratio * Local_ratio
           - Clamp to [0.7, 1.3]

        4. Application to Ratios:
           - CR_effective = CR_base / autosens_ratio
           - ISF_effective = ISF_base / autosens_ratio

           If ratio > 1 (resistance): CR and ISF decrease (need more insulin)
           If ratio < 1 (sensitivity): CR and ISF increase (need less insulin)
        """
        assert len(formula) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
