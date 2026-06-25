package org.bolusai.companion.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.bolusai.companion.diagnostics.Sanitizer
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URLEncoder
import java.net.URL
import java.nio.charset.StandardCharsets

data class DexcomBolusEvent(
    val id: String,
    val eventKind: String,
    val insulinType: String?,
    val insulinUnits: Double?,
    val carbsGrams: Int?,
    val timestamp: Long,
)

data class DexcomBolusEventsResult(
    val ok: Boolean,
    val endpoint: ActiveEndpoint,
    val events: List<DexcomBolusEvent>,
    val message: String,
)

class DexcomBolusEventClient {
    suspend fun fetch(
        primaryUrl: String,
        backupUrl: String,
        ingestKey: String,
        afterId: String?,
        afterTimestamp: Long?,
        latestOnly: Boolean = false,
    ): DexcomBolusEventsResult = withContext(Dispatchers.IO) {
        if (ingestKey.isBlank()) {
            return@withContext DexcomBolusEventsResult(false, ActiveEndpoint.NONE, emptyList(), "Falta la clave de ingesta.")
        }

        val primary = fetchFrom(primaryUrl, ingestKey, afterId, afterTimestamp, latestOnly, ActiveEndpoint.PRIMARY)
        if (primary.ok) return@withContext primary

        val backup = fetchFrom(backupUrl, ingestKey, afterId, afterTimestamp, latestOnly, ActiveEndpoint.BACKUP)
        if (backup.ok) backup else DexcomBolusEventsResult(
            ok = false,
            endpoint = ActiveEndpoint.NONE,
            events = emptyList(),
            message = Sanitizer.sanitize("Principal: ${primary.message}; Backup: ${backup.message}"),
        )
    }

    private fun fetchFrom(
        baseUrl: String,
        ingestKey: String,
        afterId: String?,
        afterTimestamp: Long?,
        latestOnly: Boolean,
        endpoint: ActiveEndpoint,
    ): DexcomBolusEventsResult = runCatching {
        val parameters = buildList {
            afterId?.takeIf { it.isNotBlank() }?.let {
                add("after_id=" + URLEncoder.encode(it, StandardCharsets.UTF_8.name()))
            }
            afterTimestamp?.takeIf { it > 0L }?.let {
                add("after_timestamp=$it")
            }
            if (latestOnly) add("latest_only=true")
        }
        val suffix = parameters.takeIf { it.isNotEmpty() }?.joinToString(prefix = "?", separator = "&").orEmpty()
        val connection = URL(baseUrl.trimEnd('/') + "/api/integrations/mobile/bolus-events$suffix")
            .openConnection() as HttpURLConnection
        connection.connectTimeout = 8_000
        connection.readTimeout = 12_000
        connection.requestMethod = "GET"
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("X-Ingest-Key", ingestKey)

        val status = connection.responseCode
        val contentType = connection.contentType.orEmpty()
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty().take(20_000)
        if (status !in 200..299) {
            return@runCatching DexcomBolusEventsResult(false, endpoint, emptyList(), Sanitizer.sanitize("HTTP $status $response"))
        }
        if (!contentType.contains("json", ignoreCase = true)) {
            return@runCatching DexcomBolusEventsResult(
                false,
                endpoint,
                emptyList(),
                "Endpoint de bolos no desplegado (Content-Type $contentType)",
            )
        }

        val events = parseDexcomEvents(response)
        DexcomBolusEventsResult(true, endpoint, events, "${events.size} eventos")
    }.getOrElse { error ->
        DexcomBolusEventsResult(false, endpoint, emptyList(), Sanitizer.sanitize(error.message ?: error::class.java.simpleName))
    }
}

internal fun parseDexcomEvents(response: String): List<DexcomBolusEvent> {
    val array = JSONArray(response)
    return buildList {
        for (index in 0 until array.length()) {
            val item = array.getJSONObject(index)
            add(
                DexcomBolusEvent(
                    id = item.getString("id"),
                    eventKind = item.getString("event_kind"),
                    insulinType = item.optString("insulin_type").takeIf { it.isNotBlank() },
                    insulinUnits = item.optDouble("insulin_units").takeIf { it.isFinite() },
                    carbsGrams = item.optInt("carbs_grams").takeIf { it > 0 },
                    timestamp = item.getLong("timestamp"),
                )
            )
        }
    }
}
