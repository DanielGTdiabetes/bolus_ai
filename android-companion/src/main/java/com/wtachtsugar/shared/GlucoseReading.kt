package com.wtachtsugar.shared

import android.os.Bundle

/**
 * Glucose reading sent from Bolus AI (mobile) to Wear OS.
 *
 * Path: /glucose
 *
 * Data format (DataMap):
 *   glucoseValue: int      - mg/dL
 *   timestamp:    long     - epoch seconds
 *   trendArrow:   String   - NONE, FLAT, RISING_SLOWLY, RISING, etc.
 *   sentAt:       long     - epoch millis when Bolus AI sent this
 *   source:       String   - "dexcom_g7" | "nightscout" | "bolusai"
 */
data class GlucoseReading(
    val glucoseValue: Int,
    val timestampSeconds: Long,
    val trendArrow: String,
    val sentAtMillis: Long,
    val source: String
) {
    companion object {
        const val DATA_PATH = "/glucose"
        const val KEY_GLUCOSE = "glucoseValue"
        const val KEY_TIMESTAMP = "timestamp"
        const val KEY_TREND = "trendArrow"
        const val KEY_SENT_AT = "sentAt"
        const val KEY_SOURCE = "source"

        fun fromBundle(bundle: Bundle): GlucoseReading? {
            val glucose = bundle.getInt(KEY_GLUCOSE, -1)
            if (glucose < 0) return null

            return GlucoseReading(
                glucoseValue = glucose,
                timestampSeconds = bundle.getLong(KEY_TIMESTAMP, 0),
                trendArrow = bundle.getString(KEY_TREND) ?: "NONE",
                sentAtMillis = bundle.getLong(KEY_SENT_AT, System.currentTimeMillis()),
                source = bundle.getString(KEY_SOURCE) ?: "unknown"
            )
        }
    }

    /** Age in minutes since the reading was taken by the sensor */
    fun ageMinutes(): Long {
        val sensorTimeMs = timestampSeconds * 1000
        return (System.currentTimeMillis() - sensorTimeMs) / 60_000
    }

    /** Age in minutes since Bolus AI sent this to the watch */
    fun sentAgeMinutes(): Long {
        return (System.currentTimeMillis() - sentAtMillis) / 60_000
    }

    /** Whether this reading is fresh enough to display */
    fun isFresh(maxAgeMinutes: Long = 15): Boolean {
        return ageMinutes() <= maxAgeMinutes
    }

    fun mmol(): Double = glucoseValue / 18.01559
}
