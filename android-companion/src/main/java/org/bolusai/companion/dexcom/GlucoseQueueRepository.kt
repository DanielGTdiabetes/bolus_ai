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
        merged.lastOrNull()?.let { persistLatest(it) }
        persist(merged)
    }

    @Synchronized
    fun pending(): List<GlucoseReading> = load()

    @Synchronized
    fun latest(maxAgeMillis: Long, nowMillis: Long = System.currentTimeMillis()): GlucoseReading? {
        val latest = loadLatest() ?: return null
        val ageMillis = nowMillis - latest.timestampSeconds * 1000
        return latest.takeIf { ageMillis in 0..maxAgeMillis }
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

    private fun loadLatest(): GlucoseReading? = runCatching {
        val item = JSONObject(prefs.getString(KEY_LATEST, "") ?: "")
        GlucoseReading(
            glucoseMgdl = item.getInt("glucose_mgdl"),
            timestampSeconds = item.getLong("timestamp"),
            trendArrow = item.optString("trend_arrow", "NONE"),
            sensorType = item.optString("sensor_type", "G7"),
            sourcePackage = item.optString("source_package", "com.dexcom.g7"),
        ).takeIf { GlucoseReading.isValid(it.glucoseMgdl, it.timestampSeconds) }
    }.getOrNull()

    private fun persistLatest(reading: GlucoseReading) {
        prefs.edit().putString(KEY_LATEST, reading.toJson().toString()).apply()
    }

    private companion object {
        const val PREFS = "bolus_ai_dexcom_glucose_queue"
        const val KEY = "pending"
        const val KEY_LATEST = "latest"
        const val MAX_QUEUE_SIZE = 2_016 // Seven days at one reading every five minutes.
    }
}
