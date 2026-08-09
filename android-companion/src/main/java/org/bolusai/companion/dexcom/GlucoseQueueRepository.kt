package org.bolusai.companion.dexcom

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

class GlucoseQueueRepository(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun enqueue(readings: List<GlucoseReading>) {
        if (readings.isEmpty()) return
        synchronized(PROCESS_LOCK) {
            val merged = GlucoseQueueCodec.merge(load(), readings, MAX_QUEUE_SIZE)
            val editor = prefs.edit().putString(KEY, GlucoseQueueCodec.encode(merged))
            merged.lastOrNull()?.let { editor.putString(KEY_LATEST, it.toJson().toString()) }
            editor.apply()
        }
    }

    fun pending(): List<GlucoseReading> = synchronized(PROCESS_LOCK) { load() }

    fun latest(maxAgeMillis: Long, nowMillis: Long = System.currentTimeMillis()): GlucoseReading? {
        return synchronized(PROCESS_LOCK) {
            val latest = loadLatest() ?: return@synchronized null
            val ageMillis = nowMillis - latest.timestampSeconds * 1000
            latest.takeIf { ageMillis in 0..maxAgeMillis }
        }
    }

    fun markSent(reading: GlucoseReading) {
        synchronized(PROCESS_LOCK) {
            val remaining = load().filterNot { it.dedupeKey == reading.dedupeKey }
            prefs.edit().putString(KEY, GlucoseQueueCodec.encode(remaining)).apply()
        }
    }

    private fun load(): List<GlucoseReading> =
        GlucoseQueueCodec.decode(prefs.getString(KEY, "[]").orEmpty())

    private fun loadLatest(): GlucoseReading? = runCatching {
        val item = JSONObject(prefs.getString(KEY_LATEST, "") ?: "")
        GlucoseReading.fromJson(item)
            .takeIf { GlucoseReading.isValid(it.glucoseMgdl, it.timestampSeconds) }
    }.getOrNull()

    private companion object {
        const val PREFS = "bolus_ai_dexcom_glucose_queue"
        const val KEY = "pending"
        const val KEY_LATEST = "latest"
        const val MAX_QUEUE_SIZE = 2_016 // Seven days at one reading every five minutes.
        val PROCESS_LOCK = Any()
    }
}

internal object GlucoseQueueCodec {
    fun merge(
        existing: List<GlucoseReading>,
        incoming: List<GlucoseReading>,
        maxSize: Int,
    ): List<GlucoseReading> = (existing + incoming)
        .filter { GlucoseReading.isValid(it.glucoseMgdl, it.timestampSeconds) }
        .distinctBy { it.dedupeKey }
        .sortedBy { it.timestampSeconds }
        .takeLast(maxSize)

    fun encode(readings: List<GlucoseReading>): String = JSONArray().apply {
        readings.forEach { put(JSONObject(it.toJson().toString())) }
    }.toString()

    fun decode(raw: String): List<GlucoseReading> = runCatching {
        val array = JSONArray(raw.ifBlank { "[]" })
        buildList {
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                val reading = GlucoseReading.fromJson(item)
                if (GlucoseReading.isValid(reading.glucoseMgdl, reading.timestampSeconds)) add(reading)
            }
        }
    }.getOrDefault(emptyList())
}
