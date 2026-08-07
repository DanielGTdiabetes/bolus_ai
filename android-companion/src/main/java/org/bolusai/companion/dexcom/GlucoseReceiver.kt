package org.bolusai.companion.dexcom

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Bundle
import com.wtachtsugar.shared.GlucoseSender
import com.wtachtsugar.shared.GlucoseReading as WearGlucoseReading
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.worker.GlucoseSyncScheduler

class GlucoseReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION) return
        val settings = AppSettingsRepository(context).current()
        if (!settings.dexcomGlucoseSyncEnabled) return

        val extras = intent.extras ?: return
        val sensorType = extras.getString("sensorType").orEmpty()
        val sourcePackage = extras.getString("packageName").orEmpty()
        if (sensorType != "G7" || sourcePackage != DEXCOM_PACKAGE) return

        val readingContainer = extras.bundleCompat("glucoseValues") ?: extras
        val directReading = readingContainer.toReading(sensorType, sourcePackage)
        val readings = if (directReading != null) {
            listOf(directReading)
        } else {
            readingContainer.keySet()
                .filter { it != "sensorType" && it != "packageName" && it != "glucoseValues" }
                .mapNotNull { key -> readingContainer.bundleCompat(key)?.toReading(sensorType, sourcePackage) }
        }
        if (readings.isEmpty()) return

        val queue = GlucoseQueueRepository(context)
        queue.enqueue(readings)
        GlucoseSyncDiagnosticsRepository(context).recordBroadcast(
            readingTimestampSeconds = readings.maxOf { it.timestampSeconds },
            queueSize = queue.pending().size,
        )
        if (settings.wearGlucoseForwardEnabled) {
            readings.forEach { reading ->
                CoroutineScope(Dispatchers.IO).launch {
                    GlucoseSender.send(
                        context.applicationContext,
                        WearGlucoseReading(
                            glucoseValue = reading.glucoseMgdl,
                            timestampSeconds = reading.timestampSeconds,
                            trendArrow = reading.trendArrow,
                            sentAtMillis = System.currentTimeMillis(),
                            source = "dexcom_g7",
                        ),
                    )
                }
            }
        }
        GlucoseSyncScheduler.syncNow(context)
    }

    @Suppress("DEPRECATION")
    private fun Bundle.bundleCompat(key: String): Bundle? = getBundle(key)

    private fun Bundle.toReading(sensorType: String, sourcePackage: String): GlucoseReading? {
        val glucose = getInt("glucoseValue", -1)
        val timestamp = getLong("timestamp", -1)
        if (!GlucoseReading.isValid(glucose, timestamp)) return null
        return GlucoseReading(
            glucoseMgdl = glucose,
            timestampSeconds = timestamp,
            trendArrow = getString("trendArrow").orEmpty().ifBlank { "NONE" },
            sensorType = sensorType,
            sourcePackage = sourcePackage,
        )
    }

    private companion object {
        const val ACTION = "com.dexcom.cgm.EXTERNAL_BROADCAST"
        const val DEXCOM_PACKAGE = "com.dexcom.g7"
    }
}
