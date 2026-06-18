package org.bolusai.companion.health

import android.content.Context
import androidx.health.connect.client.HealthConnectClient

enum class HealthConnectState { AVAILABLE, NOT_INSTALLED, NOT_SUPPORTED }

class HealthConnectAvailability(private val context: Context) {
    fun status(): HealthConnectState = when (HealthConnectClient.getSdkStatus(context)) {
        HealthConnectClient.SDK_AVAILABLE -> HealthConnectState.AVAILABLE
        HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> HealthConnectState.NOT_INSTALLED
        else -> HealthConnectState.NOT_SUPPORTED
    }
}
