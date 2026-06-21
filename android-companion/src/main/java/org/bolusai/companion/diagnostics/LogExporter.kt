package org.bolusai.companion.diagnostics

import org.json.JSONArray
import org.json.JSONObject
import org.bolusai.companion.queue.MealQueueItem

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

    fun queueToText(queueItems: List<MealQueueItem>, logs: List<HealthConnectLog>): String =
        buildString {
            appendLine("Bolus AI Companion diagnostics")
            appendLine("Queue items: ${queueItems.size}")
            queueItems.forEach { item ->
                appendLine(
                    "${item.updatedAt} ${item.status} ${item.sourcePackage} metadata.id=${item.metadataId} " +
                        "dedupe_hash=${item.dedupeHash} endpoint=${item.endpointUsed ?: "-"} attempts=${item.attemptCount} error=${item.lastError ?: "-"}",
                )
                appendLine("payload=${item.payloadJson}")
                appendLine("backend_response=${item.backendResponse ?: "-"}")
            }
            appendLine()
            appendLine("Diagnostic events: ${logs.size}")
            append(toText(logs))
        }

    fun queueToJson(queueItems: List<MealQueueItem>, logs: List<HealthConnectLog>): String =
        JSONObject()
            .put(
                "queue",
                JSONArray(
                    queueItems.map { item ->
                        JSONObject()
                            .put("id", item.id)
                            .put("external_id", item.externalId)
                            .put("metadata_id", item.metadataId)
                            .put("source_package", item.sourcePackage)
                            .put("start_time", item.startTime)
                            .put("end_time", item.endTime)
                            .put("meal_type", item.mealType.orEmpty())
                            .putNullable("carbohydrates_g", item.carbohydratesGrams)
                            .putNullable("protein_g", item.proteinGrams)
                            .putNullable("fat_g", item.fatGrams)
                            .putNullable("fiber_g", item.fiberGrams)
                            .putNullable("calories_kcal", item.caloriesKcal)
                            .put("dedupe_hash", item.dedupeHash)
                            .put("payload_json", item.payloadJson)
                            .put("status", item.status.toString())
                            .put("attempt_count", item.attemptCount)
                            .put("last_error", item.lastError.orEmpty())
                            .put("endpoint_used", item.endpointUsed.orEmpty())
                            .put("backend_response", item.backendResponse.orEmpty())
                            .put("created_at", item.createdAt)
                            .put("updated_at", item.updatedAt)
                            .put("next_retry_at", item.nextRetryAt)
                    },
                ),
            )
            .put("health_connect_logs", JSONArray(toJson(logs)))
            .toString()

    private fun JSONObject.putNullable(name: String, value: Double?): JSONObject =
        put(name, value ?: JSONObject.NULL)
}
