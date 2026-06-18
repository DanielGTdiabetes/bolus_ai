package org.bolusai.companion.diagnostics

import org.bolusai.companion.health.NutritionRecordSnapshot
import java.time.Instant

enum class HealthConnectLogStatus { DETECTED, PENDING, SENT, DUPLICATE, ERROR }

data class HealthConnectLog(
    val id: String,
    val record: NutritionRecordSnapshot,
    val status: HealthConnectLogStatus,
    val endpointUsed: String?,
    val backendResponseSanitized: String?,
    val createdAt: Instant,
)
