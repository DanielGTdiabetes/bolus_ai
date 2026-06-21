package org.bolusai.companion.bolus

data class BolusSlotProfile(
    val cr: Double,
    val cf: Double,
    val target: Double,
)

data class BolusProfile(
    val schemaVersion: Int = 1,
    val userId: String = "default",
    val configHash: String = "",
    val updatedAt: String? = null,
    val slots: Map<String, BolusSlotProfile> = defaultSlots(),
    val diaHours: Double = 4.0,
    val roundStepU: Double = 0.5,
    val maxBolusU: Double = 10.0,
    val maxCorrectionU: Double = 5.0,
    val subtractFiber: Boolean = false,
    val fiberFactor: Double = 0.5,
    val fiberThresholdG: Double = 5.0,
) {
    fun slot(name: String): BolusSlotProfile = slots[name] ?: slots["snack"] ?: BolusSlotProfile(10.0, 50.0, 100.0)
    fun isSynced(): Boolean = configHash.isNotBlank() && updatedAt != null

    companion object {
        fun defaultSlots(): Map<String, BolusSlotProfile> = mapOf(
            "breakfast" to BolusSlotProfile(cr = 10.0, cf = 50.0, target = 100.0),
            "lunch" to BolusSlotProfile(cr = 10.0, cf = 50.0, target = 100.0),
            "dinner" to BolusSlotProfile(cr = 10.0, cf = 50.0, target = 100.0),
            "snack" to BolusSlotProfile(cr = 10.0, cf = 50.0, target = 100.0),
        )
    }
}

data class BolusCalculationInput(
    val glucoseMgdl: Double?,
    val carbsG: Double,
    val fiberG: Double = 0.0,
    val manualIobU: Double = 0.0,
    val slot: String,
)

data class BolusCalculationResult(
    val slot: String,
    val targetMgdl: Double,
    val netCarbsG: Double,
    val mealBolusU: Double,
    val correctionBolusU: Double,
    val manualIobU: Double,
    val rawBolusU: Double,
    val finalBolusU: Double,
    val warnings: List<String>,
)
