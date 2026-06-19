package org.bolusai.companion.health

import android.os.Build
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.NutritionRecord

object HealthPermissions {
    private const val READ_HEALTH_DATA_IN_BACKGROUND =
        "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND"

    val nutritionReadPermissions: Set<String> = setOf(
        HealthPermission.getReadPermission(NutritionRecord::class),
    )

    val backgroundReadPermissions: Set<String> = setOf(READ_HEALTH_DATA_IN_BACKGROUND)

    fun readPermissionsForRequest(): Set<String> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            nutritionReadPermissions + backgroundReadPermissions
        } else {
            nutritionReadPermissions
        }
}
