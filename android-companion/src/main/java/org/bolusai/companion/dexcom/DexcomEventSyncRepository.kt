package org.bolusai.companion.dexcom

import android.content.Context

class DexcomEventSyncRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_dexcom_sync", Context.MODE_PRIVATE)

    fun lastEventId(): String? = prefs.getString("last_event_id", null)

    fun markProcessed(eventId: String) {
        prefs.edit().putString("last_event_id", eventId).apply()
    }
}
