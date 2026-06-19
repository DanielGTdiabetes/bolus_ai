package org.bolusai.companion.health

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import java.time.Instant

class NutritionRecordSnapshotTest {
    @Test
    fun dedupeHashIsStableForSameNutritionRecord() {
        val first = sampleRecord(carbs = 42.0)
        val second = sampleRecord(carbs = 42.0)

        assertEquals(first.dedupeHash, second.dedupeHash)
    }

    @Test
    fun dedupeHashChangesWhenMacrosAreEdited() {
        val original = sampleRecord(carbs = 42.0)
        val edited = sampleRecord(carbs = 50.0)

        assertNotEquals(original.dedupeHash, edited.dedupeHash)
    }
}

fun sampleRecord(carbs: Double = 42.0): NutritionRecordSnapshot = NutritionRecordSnapshot(
    metadataId = "mfp-1",
    sourcePackage = "com.myfitnesspal.android",
    startTime = Instant.parse("2026-06-19T12:00:00Z"),
    endTime = Instant.parse("2026-06-19T12:30:00Z"),
    mealType = "LUNCH",
    carbohydratesGrams = carbs,
    proteinGrams = 21.0,
    fatGrams = 12.0,
    fiberGrams = 6.0,
    caloriesKcal = 430.0,
)
