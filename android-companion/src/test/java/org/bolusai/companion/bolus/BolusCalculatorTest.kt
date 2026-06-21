package org.bolusai.companion.bolus

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BolusCalculatorTest {
    private val calculator = BolusCalculator()

    @Test
    fun calculatesMealCorrectionAndManualIob() {
        val profile = BolusProfile(
            slots = mapOf("lunch" to BolusSlotProfile(cr = 10.0, cf = 50.0, target = 100.0)),
            roundStepU = 0.5,
        )

        val result = calculator.calculate(
            profile,
            BolusCalculationInput(glucoseMgdl = 200.0, carbsG = 40.0, manualIobU = 1.0, slot = "lunch"),
        )

        assertEquals(4.0, result.mealBolusU, 0.001)
        assertEquals(2.0, result.correctionBolusU, 0.001)
        assertEquals(5.0, result.finalBolusU, 0.001)
        assertTrue(result.warnings.any { it.contains("IOB") })
    }

    @Test
    fun subtractsFiberWhenConfigured() {
        val profile = BolusProfile(
            slots = mapOf("dinner" to BolusSlotProfile(cr = 10.0, cf = 50.0, target = 100.0)),
            subtractFiber = true,
            fiberFactor = 0.5,
            fiberThresholdG = 5.0,
            roundStepU = 0.5,
        )

        val result = calculator.calculate(
            profile,
            BolusCalculationInput(glucoseMgdl = null, carbsG = 50.0, fiberG = 10.0, slot = "dinner"),
        )

        assertEquals(45.0, result.netCarbsG, 0.001)
        assertEquals(4.5, result.finalBolusU, 0.001)
    }

    @Test
    fun capsAtMaxBolus() {
        val profile = BolusProfile(
            slots = mapOf("snack" to BolusSlotProfile(cr = 5.0, cf = 25.0, target = 100.0)),
            maxBolusU = 6.0,
            roundStepU = 0.5,
        )

        val result = calculator.calculate(
            profile,
            BolusCalculationInput(glucoseMgdl = 300.0, carbsG = 60.0, slot = "snack"),
        )

        assertEquals(6.0, result.finalBolusU, 0.001)
        assertTrue(result.warnings.any { it.contains("maximo") })
    }

    @Test
    fun defaultProfileIsNotSynced() {
        assertEquals(false, BolusProfile().isSynced())
        assertEquals(true, BolusProfile(configHash = "abc123", updatedAt = "2026-06-21T00:00:00Z").isSynced())
    }
}
