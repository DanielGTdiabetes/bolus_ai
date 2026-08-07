package org.bolusai.companion.dexcom

import android.content.Context
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
)

class GlucoseSyncDiagnosticsRepository(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun snapshot(): GlucoseSyncDiagnostics = synchronized(PROCESS_LOCK) { read() }

    fun recordBroadcast(readingTimestampSeconds: Long, queueSize: Int) = update {
        it.copy(
            lastBroadcastAtMillis = System.currentTimeMillis(),
            lastReadingTimestampSeconds = readingTimestampSeconds,
            queueSize = queueSize,
        )
    }

    fun recordUploadAttempt(queueSize: Int) = update {
        it.copy(
            lastUploadAttemptAtMillis = System.currentTimeMillis(),
            queueSize = queueSize,
            lastError = "",
        )
    }

    fun recordUploadSuccess(endpoint: ActiveEndpoint, statusCode: Int?, queueSize: Int) = update {
        it.copy(
            lastUploadSuccessAtMillis = System.currentTimeMillis(),
            lastEndpoint = endpoint.name.lowercase(),
            lastStatusCode = statusCode,
            lastError = "",
            queueSize = queueSize,
        )
    }

    fun recordUploadFailure(statusCode: Int?, detail: String, queueSize: Int) = update {
        it.copy(
            lastStatusCode = statusCode,
            lastError = Sanitizer.sanitize(detail, 240),
            queueSize = queueSize,
        )
    }

    fun recordServiceState(state: String, detail: String = "") = update {
        it.copy(
            serviceState = state,
            serviceDetail = Sanitizer.sanitize(detail, 240),
        )
    }

    fun recordServiceTimeout(fgsType: Int) = update {
        it.copy(
            serviceState = "timed_out",
            lastServiceTimeoutAtMillis = System.currentTimeMillis(),
            serviceDetail = "Android foreground-service timeout (type=$fgsType)",
        )
    }

    private fun update(transform: (GlucoseSyncDiagnostics) -> GlucoseSyncDiagnostics) {
        synchronized(PROCESS_LOCK) {
            write(transform(read()))
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
    )

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
            .apply()
    }

    private companion object {
        const val PREFS = "bolus_ai_dexcom_glucose_diagnostics"
        val PROCESS_LOCK = Any()
    }
}
