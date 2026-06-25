package org.bolusai.companion.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.bolusai.companion.dexcom.GlucoseReading
import org.bolusai.companion.diagnostics.Sanitizer
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

data class GlucoseIngestResult(
    val ok: Boolean,
    val endpoint: ActiveEndpoint,
    val statusCode: Int?,
    val body: String,
)

fun interface GlucosePoster {
    fun post(baseUrl: String, ingestKey: String, reading: GlucoseReading, endpoint: ActiveEndpoint): GlucoseIngestResult
}

class GlucoseIngestClient(
    private val poster: GlucosePoster = HttpGlucosePoster(),
) {
    suspend fun send(
        primaryUrl: String,
        backupUrl: String,
        ingestKey: String,
        reading: GlucoseReading,
    ): GlucoseIngestResult = withContext(Dispatchers.IO) {
        if (ingestKey.isBlank()) {
            return@withContext GlucoseIngestResult(false, ActiveEndpoint.NONE, null, "Falta configurar la clave de integración.")
        }
        val primary = poster.post(primaryUrl, ingestKey, reading, ActiveEndpoint.PRIMARY)
        if (primary.ok) return@withContext primary
        val backup = poster.post(backupUrl, ingestKey, reading, ActiveEndpoint.BACKUP)
        if (backup.ok) backup else GlucoseIngestResult(
            ok = false,
            endpoint = ActiveEndpoint.NONE,
            statusCode = backup.statusCode ?: primary.statusCode,
            body = Sanitizer.sanitize("Principal: ${primary.body}; Backup: ${backup.body}"),
        )
    }
}

class HttpGlucosePoster : GlucosePoster {
    override fun post(
        baseUrl: String,
        ingestKey: String,
        reading: GlucoseReading,
        endpoint: ActiveEndpoint,
    ): GlucoseIngestResult = runCatching {
        val connection = URL(baseUrl.trimEnd('/') + "/api/integrations/mobile/glucose-entry")
            .openConnection() as HttpURLConnection
        connection.connectTimeout = 10_000
        connection.readTimeout = 20_000
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("X-Ingest-Key", ingestKey)
        OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { it.write(reading.toJson().toString()) }

        val status = connection.responseCode
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty().take(600)
        GlucoseIngestResult(
            ok = status in 200..299,
            endpoint = endpoint,
            statusCode = status,
            body = Sanitizer.sanitize(response.ifBlank { "HTTP $status" }),
        )
    }.getOrElse { error ->
        GlucoseIngestResult(false, endpoint, null, Sanitizer.sanitize(error.message ?: error::class.java.simpleName))
    }
}
