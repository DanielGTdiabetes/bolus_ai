package org.bolusai.companion.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Instant
import java.time.ZoneId

class NutritionRecordReader(private val context: Context) {
    suspend fun readLatest(syncEnabled: Boolean): List<NutritionRecordSnapshot> {
        if (!syncEnabled) return emptyList()
        val client = HealthConnectClient.getOrCreate(context)
        val window = NutritionReadWindow.latest()
        val response = client.readRecords(
            ReadRecordsRequest(
                recordType = NutritionRecord::class,
                timeRangeFilter = TimeRangeFilter.between(window.start, window.end),
            ),
        )
        return response.records.map { it.toSnapshot() }
    }
}

data class NutritionReadWindow(
    val start: Instant,
    val end: Instant,
) {
    companion object {
        fun latest(now: Instant = Instant.now(), zoneId: ZoneId = ZoneId.systemDefault()): NutritionReadWindow {
            val today = now.atZone(zoneId).toLocalDate()
            val startOfLocalDay = today
                .atStartOfDay(zoneId)
                .toInstant()
            val endOfLocalDay = today
                .plusDays(1)
                .atStartOfDay(zoneId)
                .toInstant()
            return NutritionReadWindow(
                start = startOfLocalDay,
                end = endOfLocalDay,
            )
        }
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
