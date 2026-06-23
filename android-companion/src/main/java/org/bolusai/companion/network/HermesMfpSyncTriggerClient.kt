package org.bolusai.companion.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.bolusai.companion.diagnostics.Sanitizer
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class HermesMfpSyncTriggerResult(
    val ok: Boolean,
    val statusCode: Int?,
    val body: String,
) {
    fun shouldFollowUp(): Boolean {
        if (!ok || reportedSuccess() == false) return false
        return postedCount() == 0
    }

    private fun reportedSuccess(): Boolean? =
        runCatching { JSONObject(body).optInt("success") }.getOrNull()?.let { it != 0 }

    private fun postedCount(): Int? {
        val outputTail = runCatching { JSONObject(body).optString("output_tail") }.getOrNull().orEmpty()
        val text = if (outputTail.isBlank()) body else "$body\n$outputTail"
        return POSTED_COUNT_REGEX.findAll(text)
            .mapNotNull { it.groupValues.getOrNull(1)?.toIntOrNull() }
            .lastOrNull()
    }

    private companion object {
        val POSTED_COUNT_REGEX = Regex("""\bposted\s*=\s*(\d+)""", RegexOption.IGNORE_CASE)
    }
}

class HermesMfpSyncTriggerClient {
    suspend fun trigger(baseUrl: String, ingestKey: String): HermesMfpSyncTriggerResult = withContext(Dispatchers.IO) {
        if (baseUrl.isBlank()) {
            return@withContext HermesMfpSyncTriggerResult(ok = false, statusCode = null, body = "Hermes trigger URL not configured")
        }
        if (ingestKey.isBlank()) {
            return@withContext HermesMfpSyncTriggerResult(ok = false, statusCode = null, body = "Missing ingest key")
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
            val body = Sanitizer.sanitize(stream?.bufferedReader()?.use { it.readText() }.orEmpty().take(1200))
            HermesMfpSyncTriggerResult(ok = status in 200..299, statusCode = status, body = body.ifBlank { "HTTP $status" })
        }.getOrElse { error ->
            HermesMfpSyncTriggerResult(
                ok = false,
                statusCode = null,
                body = Sanitizer.sanitize(error.message ?: error::class.java.simpleName),
            )
        }
    }
}
