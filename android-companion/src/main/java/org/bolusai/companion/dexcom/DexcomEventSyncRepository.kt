package org.bolusai.companion.dexcom

import android.content.Context

class DexcomEventSyncRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_dexcom_sync", Context.MODE_PRIVATE)

    fun lastEventId(): String? = prefs.getString("last_event_id", null)
    fun lastEventTimestamp(): Long? =
        prefs.getLong("last_event_timestamp", 0L).takeIf { it > 0L }

    fun markProcessed(eventId: String, timestamp: Long) {
        prefs.edit()
            .putString("last_event_id", eventId)
            .putLong("last_event_timestamp", timestamp)
            .apply()
    }

    fun hasRecentCarbsBroadcast(carbsGrams: Int, timestamp: Long): Boolean =
        recentCarbsBroadcasts().any { broadcast ->
            broadcast.carbsGrams == carbsGrams &&
                kotlin.math.abs(broadcast.timestamp - timestamp) <= CARBS_DEDUPE_WINDOW_MS
        }

    fun markCarbsBroadcast(carbsGrams: Int, timestamp: Long) {
        val cutoff = System.currentTimeMillis() - CARBS_DEDUPE_RETENTION_MS
        val broadcasts = recentCarbsBroadcasts()
            .filter { it.timestamp >= cutoff }
            .plus(CarbsBroadcast(carbsGrams, timestamp))
            .takeLast(MAX_CARBS_BROADCASTS)
            .map { "${it.timestamp}:${it.carbsGrams}" }
            .toSet()
        prefs.edit()
            .putStringSet("recent_carbs_broadcasts", broadcasts)
            .apply()
    }

    fun markInitialized(timestamp: Long = System.currentTimeMillis()) {
        prefs.edit()
            .remove("last_event_id")
            .putLong("last_event_timestamp", timestamp)
            .apply()
    }

    private fun recentCarbsBroadcasts(): List<CarbsBroadcast> =
        prefs.getStringSet("recent_carbs_broadcasts", emptySet())
            ?.mapNotNull { raw ->
                val parts = raw.split(":")
                if (parts.size != 2) return@mapNotNull null
                val timestamp = parts[0].toLongOrNull() ?: return@mapNotNull null
                val carbsGrams = parts[1].toIntOrNull() ?: return@mapNotNull null
                CarbsBroadcast(carbsGrams, timestamp)
            }
            .orEmpty()

    private data class CarbsBroadcast(
        val carbsGrams: Int,
        val timestamp: Long,
    )

    companion object {
        private const val MAX_CARBS_BROADCASTS = 100
        private const val CARBS_DEDUPE_WINDOW_MS = 45 * 60_000L
        private const val CARBS_DEDUPE_RETENTION_MS = 24 * 60 * 60_000L
    }
}
