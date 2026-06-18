package org.bolusai.companion.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class AppSettingsRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_settings", Context.MODE_PRIVATE)
    private val state = MutableStateFlow(read())

    fun observe(): StateFlow<AppSettings> = state.asStateFlow()

    fun updatePrimaryUrl(value: String) = update(read().copy(primaryUrl = value.trim()))
    fun updateBackupUrl(value: String) = update(read().copy(backupUrl = value.trim()))
    fun setNutritionSyncEnabled(value: Boolean) = update(read().copy(nutritionSyncEnabled = value))
    fun setLogRetentionDays(value: Int) = update(read().copy(logRetentionDays = value))

    private fun read(): AppSettings = AppSettings(
        primaryUrl = prefs.getString("primaryUrl", AppSettings().primaryUrl) ?: AppSettings().primaryUrl,
        backupUrl = prefs.getString("backupUrl", AppSettings().backupUrl) ?: AppSettings().backupUrl,
        nutritionSyncEnabled = prefs.getBoolean("nutritionSyncEnabled", false),
        logRetentionDays = prefs.getInt("logRetentionDays", 30),
    )

    private fun update(settings: AppSettings) {
        prefs.edit()
            .putString("primaryUrl", settings.primaryUrl)
            .putString("backupUrl", settings.backupUrl)
            .putBoolean("nutritionSyncEnabled", settings.nutritionSyncEnabled)
            .putInt("logRetentionDays", settings.logRetentionDays)
            .apply()
        state.value = settings
    }
}
