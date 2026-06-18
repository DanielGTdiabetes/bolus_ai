package org.bolusai.companion.diagnostics

class LogExporter {
    fun toText(logs: List<HealthConnectLog>): String = logs.joinToString("\n") { log ->
        "${log.createdAt} ${log.status} ${log.record.sourcePackage} ${log.record.metadataId} ${log.record.dedupeHash}"
    }

    fun toJson(logs: List<HealthConnectLog>): String = logs.joinToString(prefix = "[", postfix = "]") { log ->
        """
        {
          "id":"${log.id}",
          "metadata_id":"${log.record.metadataId}",
          "source_package":"${log.record.sourcePackage}",
          "start_time":"${log.record.startTime}",
          "end_time":"${log.record.endTime}",
          "meal_type":"${log.record.mealType.orEmpty()}",
          "carbohydrates_g":${log.record.carbohydratesGrams ?: "null"},
          "protein_g":${log.record.proteinGrams ?: "null"},
          "fat_g":${log.record.fatGrams ?: "null"},
          "fiber_g":${log.record.fiberGrams ?: "null"},
          "calories_kcal":${log.record.caloriesKcal ?: "null"},
          "dedupe_hash":"${log.record.dedupeHash}",
          "endpoint_used":"${log.endpointUsed.orEmpty()}",
          "status":"${log.status}",
          "backend_response_sanitized":"${log.backendResponseSanitized.orEmpty()}"
        }
        """.trimIndent()
    }
}
