package org.bolusai.companion.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.bolusai.companion.bolus.BolusProfile
import org.bolusai.companion.bolus.toBolusProfile
import org.bolusai.companion.diagnostics.Sanitizer
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class MobileBolusSettingsResult(
    val ok: Boolean,
    val endpoint: ActiveEndpoint,
    val profile: BolusProfile?,
    val message: String,
)

fun interface MobileBolusSettingsFetcher {
    fun fetch(baseUrl: String, ingestKey: String, endpoint: ActiveEndpoint): MobileBolusSettingsResult
}

class MobileBolusSettingsClient(
    private val fetcher: MobileBolusSettingsFetcher = HttpMobileBolusSettingsFetcher(),
) {
    suspend fun sync(primaryUrl: String, backupUrl: String, ingestKey: String): MobileBolusSettingsResult = withContext(Dispatchers.IO) {
        if (ingestKey.isBlank()) {
            return@withContext MobileBolusSettingsResult(false, ActiveEndpoint.NONE, null, "Falta la clave de ingesta.")
        }

        val primary = fetcher.fetch(primaryUrl, ingestKey, ActiveEndpoint.PRIMARY)
        if (primary.ok) return@withContext primary

        val backup = fetcher.fetch(backupUrl, ingestKey, ActiveEndpoint.BACKUP)
        if (backup.ok) {
            backup
        } else {
            MobileBolusSettingsResult(
                ok = false,
                endpoint = ActiveEndpoint.NONE,
                profile = null,
                message = Sanitizer.sanitize("Principal: ${primary.message}; Backup: ${backup.message}"),
            )
        }
    }
}

class HttpMobileBolusSettingsFetcher : MobileBolusSettingsFetcher {
    override fun fetch(baseUrl: String, ingestKey: String, endpoint: ActiveEndpoint): MobileBolusSettingsResult = runCatching {
        val connection = URL(baseUrl.trimEnd('/') + "/api/integrations/mobile/bolus-settings").openConnection() as HttpURLConnection
        connection.connectTimeout = 8_000
        connection.readTimeout = 12_000
        connection.requestMethod = "GET"
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("X-Ingest-Key", ingestKey)

        val status = connection.responseCode
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty().take(2_000)
        if (status !in 200..299) {
            return@runCatching MobileBolusSettingsResult(false, endpoint, null, Sanitizer.sanitize("HTTP $status $response"))
        }

        MobileBolusSettingsResult(
            ok = true,
            endpoint = endpoint,
            profile = JSONObject(response).toBolusProfile(),
            message = "Ajustes sincronizados desde ${endpoint.name.lowercase()}",
        )
    }.getOrElse { error ->
        MobileBolusSettingsResult(
            ok = false,
            endpoint = endpoint,
            profile = null,
            message = Sanitizer.sanitize(error.message ?: error::class.java.simpleName),
        )
    }
}
