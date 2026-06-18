package org.bolusai.companion.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

enum class ActiveEndpoint { PRIMARY, BACKUP, NONE }

data class ServerStatus(
    val activeEndpoint: ActiveEndpoint = ActiveEndpoint.NONE,
    val message: String = "Sin comprobar",
)

class ServerStatusClient {
    suspend fun resolve(primaryUrl: String, backupUrl: String): ServerStatus = withContext(Dispatchers.IO) {
        if (isHealthy(primaryUrl)) return@withContext ServerStatus(ActiveEndpoint.PRIMARY, "Principal activo")
        if (isHealthy(backupUrl)) return@withContext ServerStatus(ActiveEndpoint.BACKUP, "Usando servidor backup")
        ServerStatus(ActiveEndpoint.NONE, "Sin conexión: ambos servidores fallan")
    }

    private fun isHealthy(baseUrl: String): Boolean = runCatching {
        val connection = URL(baseUrl.trimEnd('/') + "/healthz").openConnection() as HttpURLConnection
        connection.connectTimeout = 3_000
        connection.readTimeout = 3_000
        connection.requestMethod = "GET"
        connection.responseCode in 200..299
    }.getOrDefault(false)
}
