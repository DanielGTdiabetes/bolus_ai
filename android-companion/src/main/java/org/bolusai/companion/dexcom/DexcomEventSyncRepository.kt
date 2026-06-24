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
}
