package org.bolusai.companion.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.bolusai.companion.diagnostics.Sanitizer
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

enum class HermesMfpSyncStatus(val wireValue: String) {
    SUCCESS("success"),
    SUCCESS_WITH_WARNING("success_with_warning"),
    NO_CHANGES("no_changes"),
    RETRY_SCHEDULED("retry_scheduled"),
    FAILED("failed"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(value: String?): HermesMfpSyncStatus =
            entries.firstOrNull { it.wireValue == value?.trim()?.lowercase() } ?: UNKNOWN
    }
}

data class HermesMfpSyncTriggerResult(
    val ok: Boolean,
    val statusCode: Int?,
    val body: String,
    val syncId: String? = null,
    val status: HermesMfpSyncStatus = HermesMfpSyncStatus.UNKNOWN,
    val metadataStatus: String? = null,
    val ingestStatus: String? = null,
    val notificationStatus: String? = null,
    val postedCount: Int? = null,
    val queuedCount: Int? = null,
    val outputTail: String = "",
    val message: String? = null,
) {
    fun shouldFollowUp(): Boolean {
        if (!ok || reportedSuccess() == false) return false
        if (ingestStatus == "no_changes" || status == HermesMfpSyncStatus.NO_CHANGES) return true
        if (ingestStatus == "retry_scheduled" || status == HermesMfpSyncStatus.RETRY_SCHEDULED) return false
        val posted = resolvedPostedCount()
        val queued = resolvedQueuedCount()
        return posted == 0 && (queued == null || queued == 0)
    }

    fun notificationSummary(): String = when (status) {
        HermesMfpSyncStatus.SUCCESS -> if (notificationPending()) {
            "comida sincronizada, aviso pendiente"
        } else {
            "comida sincronizada"
        }
        HermesMfpSyncStatus.SUCCESS_WITH_WARNING -> when (ingestStatus) {
            "success" -> if (notificationPending()) {
                "comida sincronizada, aviso pendiente"
            } else {
                "comida sincronizada con aviso"
            }
            "no_changes" -> "sin cambios; metadatos con aviso"
            else -> "sincronización completada con aviso"
        }
        HermesMfpSyncStatus.NO_CHANGES -> "sin cambios"
        HermesMfpSyncStatus.RETRY_SCHEDULED -> "reintento pendiente"
        HermesMfpSyncStatus.FAILED -> "error ${statusCode ?: "-"}"
        HermesMfpSyncStatus.UNKNOWN -> if (ok) "respuesta recibida" else "error ${statusCode ?: "-"}"
    }

    fun diagnosticSummary(): String {
        val fields = buildList {
            add("HTTP ${statusCode ?: "-"}")
            add("status=${status.wireValue}")
            syncId?.takeIf { it.isNotBlank() }?.let { add("sync_id=$it") }
            metadataStatus?.takeIf { it.isNotBlank() }?.let { add("metadata_status=$it") }
            ingestStatus?.takeIf { it.isNotBlank() }?.let { add("ingest_status=$it") }
            notificationStatus?.takeIf { it.isNotBlank() }?.let { add("notification_status=$it") }
            postedCount?.let { add("posted=$it") }
            queuedCount?.let { add("queued=$it") }
            message?.takeIf { it.isNotBlank() }?.let { add("message=$it") }
            outputTail.takeIf { it.isNotBlank() }?.let { add("output_tail=$it") }
            if (message.isNullOrBlank() && outputTail.isBlank()) {
                body.takeIf { it.isNotBlank() }?.let { add("body=$it") }
            }
        }
        return Sanitizer.sanitize(fields.joinToString(" "), maxLength = 1_200)
    }

    private fun reportedSuccess(): Boolean? {
        val json = runCatching { JSONObject(body) }.getOrNull() ?: return null
        if (!json.has("success") || json.isNull("success")) return null
        return when (val value = json.opt("success")) {
            is Boolean -> value
            is Number -> value.toInt() != 0
            is String -> value == "1" || value.equals("true", ignoreCase = true)
            else -> null
        }
    }

    private fun resolvedPostedCount(): Int? = postedCount ?: legacyCount(POSTED_COUNT_REGEX)

    private fun notificationPending(): Boolean =
        notificationStatus in setOf("queued", "retry_scheduled", "delivery_unknown")

    private fun resolvedQueuedCount(): Int? = queuedCount ?: legacyCount(QUEUED_COUNT_REGEX)

    private fun legacyCount(regex: Regex): Int? {
        val outputTail = runCatching { JSONObject(body).optString("output_tail") }.getOrNull().orEmpty()
        val text = if (outputTail.isBlank()) body else "$body\n$outputTail"
        return regex.findAll(text)
            .mapNotNull { it.groupValues.getOrNull(1)?.toIntOrNull() }
            .lastOrNull()
    }

    companion object {
        val POSTED_COUNT_REGEX = Regex("""\bposted\s*=\s*(\d+)""", RegexOption.IGNORE_CASE)
        val QUEUED_COUNT_REGEX = Regex("""\bqueued\s*=\s*(\d+)""", RegexOption.IGNORE_CASE)

        fun fromHttpResponse(statusCode: Int?, rawBody: String): HermesMfpSyncTriggerResult {
            val transportOk = statusCode != null && statusCode in 200..299
            val json = runCatching { JSONObject(rawBody) }.getOrNull()
            val outputTail = json?.optString("output_tail").orEmpty()
            val textForLegacyParsing = if (outputTail.isBlank()) rawBody else "$rawBody\n$outputTail"
            val postedCount = json.nullableInt("posted_count")
                ?: lastLegacyCount(POSTED_COUNT_REGEX, textForLegacyParsing)
            val queuedCount = json.nullableInt("queued_count")
                ?: lastLegacyCount(QUEUED_COUNT_REGEX, textForLegacyParsing)
            val reportedSuccess = json.nullableSuccess()
            val structuredStatus = HermesMfpSyncStatus.fromWire(json?.optString("status"))
            val status = if (structuredStatus != HermesMfpSyncStatus.UNKNOWN) {
                structuredStatus
            } else {
                when {
                    reportedSuccess == false -> HermesMfpSyncStatus.FAILED
                    queuedCount != null && queuedCount > 0 -> HermesMfpSyncStatus.RETRY_SCHEDULED
                    postedCount == 0 && queuedCount == 0 -> HermesMfpSyncStatus.NO_CHANGES
                    postedCount != null && postedCount > 0 -> HermesMfpSyncStatus.SUCCESS
                    reportedSuccess == true -> HermesMfpSyncStatus.SUCCESS_WITH_WARNING
                    else -> HermesMfpSyncStatus.UNKNOWN
                }
            }
            return HermesMfpSyncTriggerResult(
                ok = status != HermesMfpSyncStatus.FAILED &&
                    (transportOk || status == HermesMfpSyncStatus.RETRY_SCHEDULED),
                statusCode = statusCode,
                body = Sanitizer.sanitize(rawBody, maxLength = 1_200).ifBlank { "HTTP ${statusCode ?: "-"}" },
                syncId = json?.optString("sync_id")?.takeIf { it.isNotBlank() },
                status = status,
                metadataStatus = json?.optString("metadata_status")?.takeIf { it.isNotBlank() },
                ingestStatus = json?.optString("ingest_status")?.takeIf { it.isNotBlank() },
                notificationStatus = json?.optString("notification_status")?.takeIf { it.isNotBlank() },
                postedCount = postedCount,
                queuedCount = queuedCount,
                outputTail = Sanitizer.sanitize(outputTail, maxLength = 1_000),
                message = json?.optString("message")?.takeIf { it.isNotBlank() },
            )
        }

        private fun lastLegacyCount(regex: Regex, text: String): Int? =
            regex.findAll(text)
                .mapNotNull { it.groupValues.getOrNull(1)?.toIntOrNull() }
                .lastOrNull()

        private fun JSONObject?.nullableInt(name: String): Int? {
            if (this == null || !has(name) || isNull(name)) return null
            return opt(name)?.toString()?.toIntOrNull()
        }

        private fun JSONObject?.nullableSuccess(): Boolean? {
            if (this == null || !has("success") || isNull("success")) return null
            return when (val value = opt("success")) {
                is Boolean -> value
                is Number -> value.toInt() != 0
                is String -> value == "1" || value.equals("true", ignoreCase = true)
                else -> null
            }
        }
    }
}

class HermesMfpSyncTriggerClient {
    suspend fun trigger(baseUrl: String, ingestKey: String): HermesMfpSyncTriggerResult = withContext(Dispatchers.IO) {
        if (baseUrl.isBlank()) {
            return@withContext HermesMfpSyncTriggerResult(
                ok = false,
                statusCode = null,
                body = "Hermes trigger URL not configured",
                status = HermesMfpSyncStatus.FAILED,
                message = "Hermes trigger URL not configured",
            )
        }
        if (ingestKey.isBlank()) {
            return@withContext HermesMfpSyncTriggerResult(
                ok = false,
                statusCode = null,
                body = "Missing ingest key",
                status = HermesMfpSyncStatus.FAILED,
                message = "Missing ingest key",
            )
        }

        runCatching {
            val connection = URL(baseUrl.trimEnd('/') + "/mfp/sync-now").openConnection() as HttpURLConnection
            connection.connectTimeout = 5_000
            connection.readTimeout = 150_000
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("X-Ingest-Key", ingestKey)
            connection.outputStream.use { it.write(ByteArray(0)) }

            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val rawBody = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            HermesMfpSyncTriggerResult.fromHttpResponse(statusCode = status, rawBody = rawBody)
        }.getOrElse { error ->
            HermesMfpSyncTriggerResult(
                ok = false,
                statusCode = null,
                body = Sanitizer.sanitize(error.message ?: error::class.java.simpleName),
                status = HermesMfpSyncStatus.FAILED,
                message = Sanitizer.sanitize(error.message ?: error::class.java.simpleName),
            )
        }
    }
}
