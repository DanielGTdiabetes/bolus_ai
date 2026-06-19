package org.bolusai.companion.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.request.ChangesTokenRequest

class NutritionChangeTracker(private val context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_health_changes", Context.MODE_PRIVATE)

    suspend fun hasChanges(): Boolean {
        val client = HealthConnectClient.getOrCreate(context)
        val existingToken = prefs.getString(KEY_NUTRITION_TOKEN, null)

        if (existingToken.isNullOrBlank()) {
            prefs.edit().putString(KEY_NUTRITION_TOKEN, newToken(client)).apply()
            return true
        }

        var token = existingToken.orEmpty()
        var hasChanges = false
        do {
            val response = client.getChanges(token)
            if (response.changesTokenExpired) {
                prefs.edit().putString(KEY_NUTRITION_TOKEN, newToken(client)).apply()
                return true
            }
            hasChanges = hasChanges || response.changes.isNotEmpty()
            token = response.nextChangesToken
        } while (response.hasMore)

        prefs.edit().putString(KEY_NUTRITION_TOKEN, token).apply()
        return hasChanges
    }

    private suspend fun newToken(client: HealthConnectClient): String =
        client.getChangesToken(
            ChangesTokenRequest(recordTypes = setOf(NutritionRecord::class)),
        )

    private companion object {
        const val KEY_NUTRITION_TOKEN = "nutrition_changes_token"
    }
}
