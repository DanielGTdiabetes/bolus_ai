package com.wtachtsugar.shared

import android.content.Context
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.tasks.await

/**
 * Sends glucose readings to Wear OS via Data Layer.
 *
 * Usage in Bolus AI (mobile), inside the GlucoseReceiver:
 *
 *   GlucoseSender.send(context, GlucoseReading(
 *       glucoseValue = reading.getInt("glucoseValue"),
 *       timestampSeconds = reading.getLong("timestamp"),
 *       trendArrow = reading.getString("trendArrow"),
 *       sentAtMillis = System.currentTimeMillis(),
 *       source = "dexcom_g7"
 *   ))
 */
object GlucoseSender {

    /**
     * Send a glucose reading to the connected Wear OS device.
     * Call this from Bolus AI whenever a new glucose broadcast is received.
     */
    suspend fun send(context: Context, reading: GlucoseReading) {
        val dataClient = Wearable.getDataClient(context)

        val request = PutDataMapRequest.create(GlucoseReading.DATA_PATH).apply {
            dataMap.apply {
                putInt(GlucoseReading.KEY_GLUCOSE, reading.glucoseValue)
                putLong(GlucoseReading.KEY_TIMESTAMP, reading.timestampSeconds)
                putString(GlucoseReading.KEY_TREND, reading.trendArrow)
                putLong(GlucoseReading.KEY_SENT_AT, reading.sentAtMillis)
                putString(GlucoseReading.KEY_SOURCE, reading.source)
            }
        }
        request.setUrgent()

        dataClient.putDataItem(request.asPutDataRequest()).await()
    }
}
