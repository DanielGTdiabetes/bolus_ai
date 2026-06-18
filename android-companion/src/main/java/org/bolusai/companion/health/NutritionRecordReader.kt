package org.bolusai.companion.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Instant
import java.time.temporal.ChronoUnit

class NutritionRecordReader(private val context: Context) {
    suspend fun readLatest(syncEnabled: Boolean): List<NutritionRecordSnapshot> {
        if (!syncEnabled) return emptyList()
        val client = HealthConnectClient.getOrCreate(context)
        val end = Instant.now()
        val start = end.minus(48, ChronoUnit.HOURS)
        val response = client.readRecords(
            ReadRecordsRequest(
                recordType = NutritionRecord::class,
                timeRangeFilter = TimeRangeFilter.between(start, end),
            ),
        )
        return response.records.map { it.toSnapshot() }
    }
}

private fun NutritionRecord.toSnapshot(): NutritionRecordSnapshot = NutritionRecordSnapshot(
    metadataId = metadata.id,
    sourcePackage = metadata.dataOrigin.packageName,
    startTime = startTime,
    endTime = endTime,
    mealType = mealType.toString(),
    carbohydratesGrams = totalCarbohydrate?.inGrams,
    proteinGrams = protein?.inGrams,
    fatGrams = totalFat?.inGrams,
    fiberGrams = dietaryFiber?.inGrams,
    caloriesKcal = energy?.inKilocalories,
)
