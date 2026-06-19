package org.bolusai.companion.health

import java.time.Instant
import java.security.MessageDigest

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
    val mealSlotKey: String = listOf(
        sourcePackage,
        startTime.toString(),
        endTime.toString(),
        mealType.orEmpty(),
    ).joinToString("|")

    val stableFingerprint: String = listOf(
        mealSlotKey,
        carbohydratesGrams.toStableMacro(),
        proteinGrams.toStableMacro(),
        fatGrams.toStableMacro(),
        fiberGrams.toStableMacro(),
        caloriesKcal.toStableMacro(),
    ).joinToString("|").sha256()

    val dedupeHash: String = stableFingerprint

    private fun Double?.toStableMacro(): String =
        this?.let { "%.2f".format(java.util.Locale.US, it) }.orEmpty()

    private fun String.sha256(): String {
        val bytes = MessageDigest.getInstance("SHA-256").digest(toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { "%02x".format(it) }
    }
}
