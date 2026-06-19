package org.bolusai.companion.diagnostics

import org.json.JSONArray
import org.json.JSONObject

class LogExporter {
    fun toText(logs: List<HealthConnectLog>): String = logs.joinToString("\n") { log ->
        "${log.createdAt} ${log.status} ${log.record.sourcePackage} ${log.record.metadataId} ${log.record.dedupeHash}"
    }

    fun toJson(logs: List<HealthConnectLog>): String = JSONArray(
        logs.map { log ->
            JSONObject()
                .put("id", log.id)
                .put("metadata_id", log.record.metadataId)
                .put("source_package", log.record.sourcePackage)
                .put("start_time", log.record.startTime.toString())
                .put("end_time", log.record.endTime.toString())
                .put("meal_type", log.record.mealType.orEmpty())
                .putNullable("carbohydrates_g", log.record.carbohydratesGrams)
                .putNullable("protein_g", log.record.proteinGrams)
                .putNullable("fat_g", log.record.fatGrams)
                .putNullable("fiber_g", log.record.fiberGrams)
                .putNullable("calories_kcal", log.record.caloriesKcal)
                .put("dedupe_hash", log.record.dedupeHash)
                .put("endpoint_used", log.endpointUsed.orEmpty())
                .put("status", log.status.toString())
                .put("backend_response_sanitized", log.backendResponseSanitized.orEmpty())
                .put("created_at", log.createdAt.toString())
        },
    ).toString()

    private fun JSONObject.putNullable(name: String, value: Double?): JSONObject =
        put(name, value ?: JSONObject.NULL)
}
