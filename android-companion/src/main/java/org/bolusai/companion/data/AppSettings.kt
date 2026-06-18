package org.bolusai.companion.data

data class AppSettings(
    val primaryUrl: String = "https://bolus-ai.duckdns.org",
    val backupUrl: String = "https://bolus-ai-1.onrender.com",
    val nutritionSyncEnabled: Boolean = false,
    val logRetentionDays: Int = 30,
)
