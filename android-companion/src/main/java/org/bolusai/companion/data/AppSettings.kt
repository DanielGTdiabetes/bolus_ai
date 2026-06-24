package org.bolusai.companion.data

data class AppSettings(
    val primaryUrl: String = "https://bolus-ai.duckdns.org",
    val backupUrl: String = "https://bolus-ai-1.onrender.com",
    val hermesMfpSyncTriggerUrl: String = "http://100.65.212.74:8776",
    val ingestKey: String = "",
    val nutritionSyncEnabled: Boolean = false,
    val myFitnessPalAssistEnabled: Boolean = false,
    val dexcomWriteEnabled: Boolean = false,
    val logRetentionDays: Int = 30,
)
