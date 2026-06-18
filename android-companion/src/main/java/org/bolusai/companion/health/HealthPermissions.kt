package org.bolusai.companion.health

import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.NutritionRecord

object HealthPermissions {
    val nutritionReadPermissions: Set<String> = setOf(
        HealthPermission.getReadPermission(NutritionRecord::class),
    )
}
