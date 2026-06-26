package org.bolusai.companion.dexcom

import android.content.Context

class DexcomEventSyncRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_dexcom_sync", Context.MODE_PRIVATE)

    fun lastEventId(): String? = prefs.getString("last_event_id", null)
    fun lastEventTimestamp(): Long? =
        prefs.getLong("last_event_timestamp", 0L).takeIf { it > 0L }

    fun isProcessed(eventId: String): Boolean {
        if (eventId == lastEventId()) return true
        return processedEventIds().contains(eventId)
    }

    fun hasProcessedEventIds(): Boolean =
        processedEventIds().isNotEmpty()

    fun markProcessedBatch(eventIds: Collection<String>) {
        if (eventIds.isEmpty()) return
        val processedIds = processedEventIds()
            .plus(eventIds)
            .takeLast(MAX_PROCESSED_IDS)
            .toSet()
        prefs.edit()
            .putStringSet("processed_event_ids", processedIds)
            .apply()
    }

    fun markProcessed(eventId: String, timestamp: Long) {
        val processedIds = processedEventIds()
            .plus(eventId)
            .takeLast(MAX_PROCESSED_IDS)
            .toSet()
        prefs.edit()
            .putString("last_event_id", eventId)
            .putLong("last_event_timestamp", timestamp)
            .putStringSet("processed_event_ids", processedIds)
            .apply()
    }

    fun markInitialized(timestamp: Long = System.currentTimeMillis()) {
        prefs.edit()
            .remove("last_event_id")
            .putLong("last_event_timestamp", timestamp)
            .apply()
    }

    private fun processedEventIds(): List<String> =
        prefs.getStringSet("processed_event_ids", emptySet())
            ?.toList()
            .orEmpty()

    companion object {
        private const val MAX_PROCESSED_IDS = 200
    }
}
