package org.bolusai.companion.dexcom

import org.json.JSONObject

data class GlucoseReading(
    val glucoseMgdl: Int,
    val timestampSeconds: Long,
    val trendArrow: String,
    val sensorType: String = "G7",
    val sourcePackage: String = "com.dexcom.g7",
) {
    val dedupeKey: String = "$sourcePackage:$timestampSeconds:$glucoseMgdl"

    fun toJson(): JSONObject = JSONObject()
        .put("glucose_mgdl", glucoseMgdl)
        .put("timestamp", timestampSeconds)
        .put("trend_arrow", trendArrow)
        .put("sensor_type", sensorType)
        .put("source_package", sourcePackage)

    companion object {
        fun isValid(glucoseMgdl: Int, timestampSeconds: Long): Boolean =
            glucoseMgdl in 1..400 && timestampSeconds > 0
    }
}
