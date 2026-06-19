package org.bolusai.companion.health

import org.json.JSONArray
import org.json.JSONObject
import java.time.ZoneId
import java.time.format.DateTimeFormatter

class AutoExportPayloadBuilder(
    private val zoneId: ZoneId = ZoneId.systemDefault(),
) {
    private val formatter: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss Z")

    fun build(records: List<NutritionRecordSnapshot>): String {
        val uniqueRecords = records.distinctBy { it.dedupeHash }
        val metrics = JSONArray()
        metrics.put(metric("fiber", uniqueRecords) { it.fiberGrams })
        metrics.put(metric("total_fat", uniqueRecords) { it.fatGrams })
        metrics.put(metric("carbohydrates", uniqueRecords) { it.carbohydratesGrams })
        metrics.put(metric("protein", uniqueRecords) { it.proteinGrams })

        return JSONObject()
            .put("data", JSONObject().put("metrics", metrics))
            .toString()
    }

    private fun metric(
        name: String,
        records: List<NutritionRecordSnapshot>,
        value: (NutritionRecordSnapshot) -> Double?,
    ): JSONObject {
        val data = JSONArray()
        records.forEach { record ->
            data.put(
                JSONObject()
                    .put("qty", value(record) ?: 0.0)
                    .put("date", formatter.format(record.startTime.atZone(zoneId)))
                    .put("source", sourceName(record.sourcePackage))
                    .put("meal_fingerprint", record.stableFingerprint)
                    .put("meal_type", record.mealType.orEmpty()),
            )
        }
        return JSONObject()
            .put("name", name)
            .put("units", "g")
            .put("data", data)
    }

    private fun sourceName(packageName: String): String =
        if (packageName == "com.myfitnesspal.android") "MyFitnessPal" else packageName
}
