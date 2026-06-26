package org.bolusai.companion.dexcom

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

class GlucoseQueueRepository(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    @Synchronized
    fun enqueue(readings: List<GlucoseReading>) {
        if (readings.isEmpty()) return
        val merged = (load() + readings)
            .distinctBy { it.dedupeKey }
            .sortedBy { it.timestampSeconds }
            .takeLast(MAX_QUEUE_SIZE)
        persist(merged)
    }

    @Synchronized
    fun pending(): List<GlucoseReading> = load()

    @Synchronized
    fun latest(maxAgeMs: Long): GlucoseReading? {
        val cutoffSeconds = (System.currentTimeMillis() - maxAgeMs) / 1000
        return load()
            .filter { it.timestampSeconds >= cutoffSeconds }
            .maxByOrNull { it.timestampSeconds }
    }

    @Synchronized
    fun markSent(reading: GlucoseReading) {
        persist(load().filterNot { it.dedupeKey == reading.dedupeKey })
    }

    private fun load(): List<GlucoseReading> = runCatching {
        val array = JSONArray(prefs.getString(KEY, "[]"))
        buildList {
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                val reading = GlucoseReading(
                    glucoseMgdl = item.getInt("glucose_mgdl"),
                    timestampSeconds = item.getLong("timestamp"),
                    trendArrow = item.optString("trend_arrow", "NONE"),
                    sensorType = item.optString("sensor_type", "G7"),
                    sourcePackage = item.optString("source_package", "com.dexcom.g7"),
                )
                if (GlucoseReading.isValid(reading.glucoseMgdl, reading.timestampSeconds)) add(reading)
            }
        }
    }.getOrDefault(emptyList())

    private fun persist(readings: List<GlucoseReading>) {
        val array = JSONArray()
        readings.forEach { array.put(JSONObject(it.toJson().toString())) }
        prefs.edit().putString(KEY, array.toString()).apply()
    }

    private companion object {
        const val PREFS = "bolus_ai_dexcom_glucose_queue"
        const val KEY = "pending"
        const val MAX_QUEUE_SIZE = 2_016 // Seven days at one reading every five minutes.
    }
}
