package org.bolusai.companion.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.bolusai.companion.diagnostics.Sanitizer
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

data class NutritionIngestResult(
    val ok: Boolean,
    val endpoint: ActiveEndpoint,
    val statusCode: Int?,
    val body: String,
)

fun interface NutritionPoster {
    fun post(baseUrl: String, ingestKey: String, payloadJson: String, endpoint: ActiveEndpoint): NutritionIngestResult
}

class NutritionIngestClient(
    private val poster: NutritionPoster = HttpNutritionPoster(),
) {
    suspend fun send(
        primaryUrl: String,
        backupUrl: String,
        ingestKey: String,
        payloadJson: String,
    ): NutritionIngestResult = withContext(Dispatchers.IO) {
        if (ingestKey.isBlank()) {
            return@withContext NutritionIngestResult(
                ok = false,
                endpoint = ActiveEndpoint.NONE,
                statusCode = null,
                body = "Falta configurar la clave de ingesta.",
            )
        }

        val primary = poster.post(primaryUrl, ingestKey, payloadJson, ActiveEndpoint.PRIMARY)
        if (primary.ok) return@withContext primary

        val backup = poster.post(backupUrl, ingestKey, payloadJson, ActiveEndpoint.BACKUP)
        if (backup.ok) {
            backup
        } else {
            NutritionIngestResult(
                ok = false,
                endpoint = ActiveEndpoint.NONE,
                statusCode = backup.statusCode ?: primary.statusCode,
                body = Sanitizer.sanitize("Principal: ${primary.body}; Backup: ${backup.body}"),
            )
        }
    }
}

class HttpNutritionPoster : NutritionPoster {
    override fun post(
        baseUrl: String,
        ingestKey: String,
        payloadJson: String,
        endpoint: ActiveEndpoint,
    ): NutritionIngestResult = runCatching {
        val connection = URL(baseUrl.trimEnd('/') + "/api/integrations/nutrition").openConnection() as HttpURLConnection
        connection.connectTimeout = 10_000
        connection.readTimeout = 20_000
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("X-Ingest-Key", ingestKey)

        OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
            writer.write(payloadJson)
        }

        val status = connection.responseCode
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty().take(600)
        val hasJsonResponse = response.isBlank() || response.trimStart().startsWith("{") || response.trimStart().startsWith("[")
        NutritionIngestResult(
            ok = status in 200..299 && hasJsonResponse,
            endpoint = endpoint,
            statusCode = status,
            body = Sanitizer.sanitize(
                when {
                    response.isBlank() -> "HTTP $status"
                    !hasJsonResponse -> "Respuesta no JSON: $response"
                    else -> response
                },
            ),
        )
    }.getOrElse { error ->
        NutritionIngestResult(
            ok = false,
            endpoint = endpoint,
            statusCode = null,
            body = Sanitizer.sanitize(error.message ?: error::class.java.simpleName),
        )
    }
}
