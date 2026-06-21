package org.bolusai.companion.bolus

import kotlin.math.max
import kotlin.math.min
import kotlin.math.round

class BolusCalculator {
    fun calculate(profile: BolusProfile, input: BolusCalculationInput): BolusCalculationResult {
        val warnings = mutableListOf<String>()
        val slot = profile.slot(input.slot)

        val cr = slot.cr.takeIf { it > 0.0 } ?: 10.0
        val cf = slot.cf.takeIf { it > 0.0 } ?: 50.0
        val target = slot.target.takeIf { it > 0.0 } ?: 100.0
        val carbs = max(0.0, input.carbsG)
        val fiber = max(0.0, input.fiberG)
        val manualIob = max(0.0, input.manualIobU)

        val fiberDeduction = if (profile.subtractFiber && fiber >= profile.fiberThresholdG) {
            fiber * profile.fiberFactor.coerceIn(0.0, 1.0)
        } else {
            0.0
        }
        val netCarbs = max(0.0, carbs - fiberDeduction)
        val mealBolus = netCarbs / cr

        val correction = input.glucoseMgdl
            ?.takeIf { it > target }
            ?.let { min((it - target) / cf, profile.maxCorrectionU) }
            ?: 0.0

        if (input.glucoseMgdl != null && input.glucoseMgdl < target) {
            warnings.add("Glucosa por debajo del objetivo: no se suma correccion.")
        }
        if (manualIob > 0.0) {
            warnings.add("IOB introducido manualmente y restado al calculo.")
        }
        if (input.glucoseMgdl == null) {
            warnings.add("Sin glucosa: solo se calcula la parte de comida.")
        }

        val raw = max(0.0, mealBolus + correction - manualIob)
        val rounded = roundToStep(raw, profile.roundStepU)
        val final = min(rounded, profile.maxBolusU)
        if (rounded > profile.maxBolusU) {
            warnings.add("Limitado por maximo de bolo configurado.")
        }

        return BolusCalculationResult(
            slot = input.slot,
            targetMgdl = target,
            netCarbsG = netCarbs,
            mealBolusU = mealBolus,
            correctionBolusU = correction,
            manualIobU = manualIob,
            rawBolusU = raw,
            finalBolusU = final,
            warnings = warnings,
        )
    }

    private fun roundToStep(value: Double, step: Double): Double {
        val safeStep = step.takeIf { it > 0.0 } ?: 0.5
        return round(value / safeStep) * safeStep
    }
}
