package org.bolusai.companion.diagnostics

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.bolusai.companion.health.NutritionRecordSnapshot
import java.time.Instant
import java.util.UUID

class HealthConnectLogRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_health_logs", Context.MODE_PRIVATE)
    private val logs = MutableStateFlow(load())

    fun observe(): StateFlow<List<HealthConnectLog>> = logs.asStateFlow()

    fun sentDedupeHashes(): Set<String> =
        logs.value
            .filter { it.status == HealthConnectLogStatus.SENT }
            .map { it.record.dedupeHash }
            .toSet()

    fun recordDetected(
        record: NutritionRecordSnapshot,
        status: HealthConnectLogStatus = HealthConnectLogStatus.DETECTED,
        endpointUsed: String? = null,
        backendResponseSanitized: String? = null,
    ) {
        val existing = logs.value.filterNot { it.record.dedupeHash == record.dedupeHash }
        logs.value = (listOf(
            HealthConnectLog(
                id = UUID.randomUUID().toString(),
                record = record,
                status = status,
                endpointUsed = endpointUsed,
                backendResponseSanitized = backendResponseSanitized,
                createdAt = Instant.now(),
            ),
        ) + existing).take(200)
        persist(logs.value)
    }

    fun clear() {
        logs.value = emptyList()
        prefs.edit().remove(KEY).apply()
    }

    private fun persist(value: List<HealthConnectLog>) {
        prefs.edit().putString(KEY, LogExporter().toJson(value)).apply()
    }

    private fun load(): List<HealthConnectLog> = runCatching {
        val raw = prefs.getString(KEY, null).orEmpty()
        if (raw.isBlank()) return@runCatching emptyList()

        val array = JSONArray(raw)
        buildList {
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                val record = NutritionRecordSnapshot(
                    metadataId = item.optString("metadata_id"),
                    sourcePackage = item.optString("source_package"),
                    startTime = Instant.parse(item.optString("start_time")),
                    endTime = Instant.parse(item.optString("end_time")),
                    mealType = item.optString("meal_type").ifBlank { null },
                    carbohydratesGrams = item.optNullableDouble("carbohydrates_g"),
                    proteinGrams = item.optNullableDouble("protein_g"),
                    fatGrams = item.optNullableDouble("fat_g"),
                    fiberGrams = item.optNullableDouble("fiber_g"),
                    caloriesKcal = item.optNullableDouble("calories_kcal"),
                )
                add(
                    HealthConnectLog(
                        id = item.optString("id").ifBlank { UUID.randomUUID().toString() },
                        record = record,
                        status = runCatching {
                            HealthConnectLogStatus.valueOf(item.optString("status"))
                        }.getOrDefault(HealthConnectLogStatus.DETECTED),
                        endpointUsed = item.optString("endpoint_used").ifBlank { null },
                        backendResponseSanitized = item.optString("backend_response_sanitized").ifBlank { null },
                        createdAt = runCatching {
                            Instant.parse(item.optString("created_at"))
                        }.getOrDefault(Instant.now()),
                    ),
                )
            }
        }
    }.getOrDefault(emptyList())

    private fun org.json.JSONObject.optNullableDouble(name: String): Double? =
        if (isNull(name) || !has(name)) null else optDouble(name)

    private companion object {
        const val KEY = "logs_json"
    }
}
