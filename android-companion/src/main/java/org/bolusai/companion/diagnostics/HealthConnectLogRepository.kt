package org.bolusai.companion.diagnostics

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.bolusai.companion.health.NutritionRecordSnapshot
import java.time.Instant
import java.util.UUID

class HealthConnectLogRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_health_logs", Context.MODE_PRIVATE)
    private val logs = MutableStateFlow(load())

    fun observe(): StateFlow<List<HealthConnectLog>> = logs.asStateFlow()

    fun recordDetected(record: NutritionRecordSnapshot) {
        logs.value = (listOf(
            HealthConnectLog(
                id = UUID.randomUUID().toString(),
                record = record,
                status = HealthConnectLogStatus.DETECTED,
                endpointUsed = null,
                backendResponseSanitized = null,
                createdAt = Instant.now(),
            ),
        ) + logs.value).take(200)
        persist(logs.value)
    }

    fun clear() {
        logs.value = emptyList()
        prefs.edit().remove(KEY).apply()
    }

    private fun persist(value: List<HealthConnectLog>) {
        prefs.edit().putString(KEY, LogExporter().toJson(value)).apply()
    }

    private fun load(): List<HealthConnectLog> = emptyList()

    private companion object {
        const val KEY = "logs_json"
    }
}
