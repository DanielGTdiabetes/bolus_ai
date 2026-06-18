package org.bolusai.companion.health

import java.time.Instant

data class NutritionRecordSnapshot(
    val metadataId: String,
    val sourcePackage: String,
    val startTime: Instant,
    val endTime: Instant,
    val mealType: String?,
    val carbohydratesGrams: Double?,
    val proteinGrams: Double?,
    val fatGrams: Double?,
    val fiberGrams: Double?,
    val caloriesKcal: Double?,
) {
    val dedupeHash: String = listOf(
        metadataId,
        sourcePackage,
        startTime.toString(),
        endTime.toString(),
        mealType.orEmpty(),
        carbohydratesGrams?.toString().orEmpty(),
        proteinGrams?.toString().orEmpty(),
        fatGrams?.toString().orEmpty(),
        fiberGrams?.toString().orEmpty(),
        caloriesKcal?.toString().orEmpty(),
    ).joinToString("|").hashCode().toString()
}
