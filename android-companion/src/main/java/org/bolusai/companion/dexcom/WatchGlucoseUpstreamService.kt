package org.bolusai.companion.dexcom

import android.util.Log
import com.google.android.gms.wearable.DataEvent
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.WearableListenerService
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.worker.GlucoseSyncScheduler

/** Receives validated direct-G7 readings sent upstream by WtachSugar. */
class WatchGlucoseUpstreamService : WearableListenerService() {
    override fun onDataChanged(dataEvents: DataEventBuffer) {
        val settings = AppSettingsRepository(this).current()
        if (!settings.dexcomGlucoseSyncEnabled) return
        val queue = GlucoseQueueRepository(this)
        val diagnostics = GlucoseSyncDiagnosticsRepository(this)

        val accepted = buildList {
            dataEvents.forEach { event ->
                if (event.type != DataEvent.TYPE_CHANGED) return@forEach
                if (event.dataItem.uri.path != UPSTREAM_PATH) return@forEach
                val map = DataMapItem.fromDataItem(event.dataItem).dataMap
                val source = map.getString(KEY_SOURCE, "")
                val glucose = map.getInt(KEY_GLUCOSE, -1)
                val timestamp = map.getLong(KEY_TIMESTAMP, -1)
                val sensorType = map.getString(KEY_SENSOR_TYPE, "G7")
                if (source != WATCH_SOURCE || sensorType.uppercase() != "G7") {
                    diagnostics.recordRejected(source.ifBlank { "watch_unknown" }, "origen o sensor no admitido", queue.pending().size)
                    return@forEach
                }
                if (!GlucoseReading.isValid(glucose, timestamp)) {
                    diagnostics.recordRejected(source, "glucosa o fecha no valida", queue.pending().size)
                    return@forEach
                }

                val sensorState = map.getString(KEY_SENSOR_STATE, "").ifBlank { null }
                val displayOnly = map.getBoolean(KEY_DISPLAY_ONLY, false)
                if (displayOnly || sensorState?.uppercase()?.let { it in BLOCKED_STATES } == true) {
                    diagnostics.recordRejected(source, "estado=${sensorState ?: "displayOnly"}", queue.pending().size)
                    return@forEach
                }

                add(
                    GlucoseReading(
                        glucoseMgdl = glucose,
                        timestampSeconds = timestamp,
                        trendArrow = map.getString(KEY_TREND_ARROW, "NONE"),
                        sensorType = sensorType,
                        sourcePackage = map.getString(KEY_SOURCE_PACKAGE, "org.wtachtsugar"),
                        source = WATCH_SOURCE,
                        schemaVersion = map.getInt(KEY_SCHEMA_VERSION, 2),
                        readingUid = map.getString(KEY_READING_UID, "").ifBlank { null },
                        receivedAtSeconds = System.currentTimeMillis() / 1000,
                        trendRate = map.getDouble(KEY_TREND_RATE, Double.NaN).takeUnless { it.isNaN() },
                        sensorState = sensorState,
                        displayOnly = false,
                        historical = map.getBoolean(KEY_HISTORICAL, false),
                        timestampUncertain = map.getBoolean(KEY_TIMESTAMP_UNCERTAIN, false),
                        sensorSessionId = map.getString(KEY_SENSOR_SESSION, "").ifBlank { null },
                        sequence = map.getInt(KEY_SEQUENCE, -1).takeIf { it >= 0 },
                    ),
                )
            }
        }
        if (accepted.isEmpty()) return

        queue.enqueue(accepted)
        diagnostics.recordBroadcast(
            readingTimestampSeconds = accepted.maxOf { it.timestampSeconds },
            queueSize = queue.pending().size,
            source = WATCH_SOURCE,
        )
        Log.i(TAG, "Queued ${accepted.size} direct-watch glucose reading(s)")
        GlucoseSyncScheduler.syncNow(this)
    }

    private companion object {
        const val TAG = "WatchGlucoseUpstream"
        const val UPSTREAM_PATH = "/glucose/upstream/v1"
        const val WATCH_SOURCE = "g7_direct_watch"
        const val KEY_SCHEMA_VERSION = "schemaVersion"
        const val KEY_READING_UID = "readingId"
        const val KEY_GLUCOSE = "glucoseValue"
        const val KEY_TIMESTAMP = "timestamp"
        const val KEY_TREND_ARROW = "trendArrow"
        const val KEY_TREND_RATE = "trendRate"
        const val KEY_SENSOR_STATE = "sensorState"
        const val KEY_DISPLAY_ONLY = "displayOnly"
        const val KEY_HISTORICAL = "historical"
        const val KEY_TIMESTAMP_UNCERTAIN = "timestampUncertain"
        const val KEY_SENSOR_SESSION = "sensorSessionId"
        const val KEY_SEQUENCE = "sequence"
        const val KEY_SENSOR_TYPE = "sensorType"
        const val KEY_SOURCE_PACKAGE = "sourcePackage"
        const val KEY_SOURCE = "source"
        val BLOCKED_STATES = setOf(
            "WARMUP", "STARTUP", "STOPPED", "FAILED", "ERROR", "EXPIRED",
            "NO_READINGS", "NOT_ACTIVE", "SENSOR_FAILED",
        )
    }
}
