package org.bolusai.companion.dexcom

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import org.bolusai.companion.diagnostics.Sanitizer
import org.bolusai.companion.network.ActiveEndpoint

data class GlucoseSyncDiagnostics(
    val lastBroadcastAtMillis: Long = 0,
    val lastReadingTimestampSeconds: Long = 0,
    val lastUploadAttemptAtMillis: Long = 0,
    val lastUploadSuccessAtMillis: Long = 0,
    val lastEndpoint: String = "",
    val lastStatusCode: Int? = null,
    val lastError: String = "",
    val queueSize: Int = 0,
    val serviceState: String = "unknown",
    val lastServiceTimeoutAtMillis: Long = 0,
    val serviceDetail: String = "",
    val events: List<GlucoseDiagnosticEvent> = emptyList(),
)

data class GlucoseDiagnosticEvent(
    val atMillis: Long,
    val type: String,
    val detail: String,
)

class GlucoseSyncDiagnosticsRepository(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun snapshot(): GlucoseSyncDiagnostics = synchronized(PROCESS_LOCK) { read() }

    fun clearEvents() = synchronized(PROCESS_LOCK) {
        write(read().copy(events = emptyList()))
    }

    fun recordBroadcast(
        readingTimestampSeconds: Long,
        queueSize: Int,
        source: String = "dexcom_android",
    ) = update("received", "$source · lectura=$readingTimestampSeconds · cola=$queueSize") {
        it.copy(
            lastBroadcastAtMillis = System.currentTimeMillis(),
            lastReadingTimestampSeconds = readingTimestampSeconds,
            queueSize = queueSize,
        )
    }

    fun recordUploadAttempt(queueSize: Int) = update("upload_attempt", "cola=$queueSize") {
        it.copy(
            lastUploadAttemptAtMillis = System.currentTimeMillis(),
            queueSize = queueSize,
            lastError = "",
        )
    }

    fun recordUploadSuccess(
        endpoint: ActiveEndpoint,
        statusCode: Int?,
        queueSize: Int,
        detail: String = "",
    ) = update(
        "upload_success",
        "${endpoint.name.lowercase()} · HTTP ${statusCode ?: "-"} · cola=$queueSize" +
            detail.takeIf { it.isNotBlank() }?.let { " · ${Sanitizer.sanitize(it, 120)}" }.orEmpty(),
    ) {
        it.copy(
            lastUploadSuccessAtMillis = System.currentTimeMillis(),
            lastEndpoint = endpoint.name.lowercase(),
            lastStatusCode = statusCode,
            lastError = "",
            queueSize = queueSize,
        )
    }

    fun recordUploadFailure(statusCode: Int?, detail: String, queueSize: Int) = update(
        "upload_failure",
        "HTTP ${statusCode ?: "-"} · cola=$queueSize · ${Sanitizer.sanitize(detail, 160)}",
    ) {
        it.copy(
            lastStatusCode = statusCode,
            lastError = Sanitizer.sanitize(detail, 240),
            queueSize = queueSize,
        )
    }

    fun recordServiceState(state: String, detail: String = "") = update(
        "service_$state",
        Sanitizer.sanitize(detail.ifBlank { state }, 160),
    ) {
        it.copy(
            serviceState = state,
            serviceDetail = Sanitizer.sanitize(detail, 240),
        )
    }

    fun recordServiceTimeout(fgsType: Int) = update(
        "service_timeout",
        "foreground-service type=$fgsType",
    ) {
        it.copy(
            serviceState = "timed_out",
            lastServiceTimeoutAtMillis = System.currentTimeMillis(),
            serviceDetail = "Android foreground-service timeout (type=$fgsType)",
        )
    }

    fun recordRejected(source: String, detail: String, queueSize: Int) = update(
        "rejected",
        "$source · ${Sanitizer.sanitize(detail, 160)} · cola=$queueSize",
    ) {
        it.copy(queueSize = queueSize)
    }

    private fun update(
        eventType: String,
        eventDetail: String,
        transform: (GlucoseSyncDiagnostics) -> GlucoseSyncDiagnostics,
    ) {
        synchronized(PROCESS_LOCK) {
            val current = read()
            val updated = transform(current).copy(
                events = (
                    listOf(
                        GlucoseDiagnosticEvent(
                            atMillis = System.currentTimeMillis(),
                            type = eventType,
                            detail = Sanitizer.sanitize(eventDetail, 240),
                        ),
                    ) + current.events
                ).take(MAX_EVENTS),
            )
            write(updated)
        }
    }

    private fun read(): GlucoseSyncDiagnostics = GlucoseSyncDiagnostics(
        lastBroadcastAtMillis = prefs.getLong("last_broadcast_at", 0),
        lastReadingTimestampSeconds = prefs.getLong("last_reading_timestamp", 0),
        lastUploadAttemptAtMillis = prefs.getLong("last_upload_attempt_at", 0),
        lastUploadSuccessAtMillis = prefs.getLong("last_upload_success_at", 0),
        lastEndpoint = prefs.getString("last_endpoint", "").orEmpty(),
        lastStatusCode = prefs.getInt("last_status_code", 0).takeIf { it > 0 },
        lastError = prefs.getString("last_error", "").orEmpty(),
        queueSize = prefs.getInt("queue_size", 0),
        serviceState = prefs.getString("service_state", "unknown").orEmpty(),
        lastServiceTimeoutAtMillis = prefs.getLong("last_service_timeout_at", 0),
        serviceDetail = prefs.getString("service_detail", "").orEmpty(),
        events = readEvents(),
    )

    private fun readEvents(): List<GlucoseDiagnosticEvent> = runCatching {
        val array = JSONArray(prefs.getString("events", "[]").orEmpty().ifBlank { "[]" })
        buildList {
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                add(
                    GlucoseDiagnosticEvent(
                        atMillis = item.optLong("at"),
                        type = item.optString("type"),
                        detail = item.optString("detail"),
                    ),
                )
            }
        }
    }.getOrDefault(emptyList())

    private fun write(value: GlucoseSyncDiagnostics) {
        prefs.edit()
            .putLong("last_broadcast_at", value.lastBroadcastAtMillis)
            .putLong("last_reading_timestamp", value.lastReadingTimestampSeconds)
            .putLong("last_upload_attempt_at", value.lastUploadAttemptAtMillis)
            .putLong("last_upload_success_at", value.lastUploadSuccessAtMillis)
            .putString("last_endpoint", value.lastEndpoint)
            .putInt("last_status_code", value.lastStatusCode ?: 0)
            .putString("last_error", value.lastError)
            .putInt("queue_size", value.queueSize)
            .putString("service_state", value.serviceState)
            .putLong("last_service_timeout_at", value.lastServiceTimeoutAtMillis)
            .putString("service_detail", value.serviceDetail)
            .putString(
                "events",
                JSONArray().apply {
                    value.events.forEach { event ->
                        put(
                            JSONObject()
                                .put("at", event.atMillis)
                                .put("type", event.type)
                                .put("detail", event.detail),
                        )
                    }
                }.toString(),
            )
            .apply()
    }

    private companion object {
        const val PREFS = "bolus_ai_dexcom_glucose_diagnostics"
        const val MAX_EVENTS = 30
        val PROCESS_LOCK = Any()
    }
}
