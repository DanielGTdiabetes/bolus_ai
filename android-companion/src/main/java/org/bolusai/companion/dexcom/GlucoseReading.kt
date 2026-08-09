package org.bolusai.companion.dexcom

import org.json.JSONObject

data class GlucoseReading(
    val glucoseMgdl: Int,
    val timestampSeconds: Long,
    val trendArrow: String,
    val sensorType: String = "G7",
    val sourcePackage: String = "com.dexcom.g7",
    val source: String = "dexcom_android",
    val schemaVersion: Int = 2,
    val readingUid: String? = null,
    val receivedAtSeconds: Long = System.currentTimeMillis() / 1000,
    val trendRate: Double? = null,
    val sensorState: String? = null,
    val displayOnly: Boolean = false,
    val historical: Boolean = false,
    val timestampUncertain: Boolean = false,
    val sensorSessionId: String? = null,
    val sequence: Int? = null,
) {
    val dedupeKey: String = readingUid
        ?: listOf(source, sensorSessionId.orEmpty(), sequence?.toString().orEmpty(), timestampSeconds, glucoseMgdl)
            .joinToString(":")

    fun toJson(): JSONObject = JSONObject()
        .put("schema_version", schemaVersion)
        .putOpt("reading_uid", readingUid)
        .put("glucose_mgdl", glucoseMgdl)
        .put("timestamp", timestampSeconds)
        .put("received_at", receivedAtSeconds)
        .put("trend_arrow", trendArrow)
        .putOpt("trend_rate", trendRate)
        .putOpt("sensor_state", sensorState)
        .put("display_only", displayOnly)
        .put("historical", historical)
        .put("timestamp_uncertain", timestampUncertain)
        .putOpt("sensor_session_id", sensorSessionId)
        .putOpt("sequence", sequence)
        .put("sensor_type", sensorType)
        .put("source_package", sourcePackage)
        .put("source", source)

    companion object {
        fun isValid(glucoseMgdl: Int, timestampSeconds: Long): Boolean =
            glucoseMgdl in 1..400 && timestampSeconds > 0

        fun fromJson(item: JSONObject): GlucoseReading = GlucoseReading(
            glucoseMgdl = item.getInt("glucose_mgdl"),
            timestampSeconds = item.getLong("timestamp"),
            trendArrow = item.optString("trend_arrow", "NONE"),
            sensorType = item.optString("sensor_type", "G7"),
            sourcePackage = item.optString("source_package", "com.dexcom.g7"),
            source = item.optString("source", "dexcom_android"),
            schemaVersion = item.optInt("schema_version", 2),
            readingUid = item.optString("reading_uid").takeIf { it.isNotBlank() },
            receivedAtSeconds = item.optLong("received_at", System.currentTimeMillis() / 1000),
            trendRate = item.optDouble("trend_rate").takeUnless { it.isNaN() },
            sensorState = item.optString("sensor_state").takeIf { it.isNotBlank() },
            displayOnly = item.optBoolean("display_only", false),
            historical = item.optBoolean("historical", false),
            timestampUncertain = item.optBoolean("timestamp_uncertain", false),
            sensorSessionId = item.optString("sensor_session_id").takeIf { it.isNotBlank() },
            sequence = item.optInt("sequence", -1).takeIf { it >= 0 },
        )
    }
}
