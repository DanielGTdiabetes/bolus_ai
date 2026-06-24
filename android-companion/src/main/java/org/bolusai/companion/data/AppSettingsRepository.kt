package org.bolusai.companion.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.bolusai.companion.security.SecretStore

class AppSettingsRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_settings", Context.MODE_PRIVATE)
    private val secretStore = SecretStore(context)
    private val state = MutableStateFlow(read())

    init {
        migrateLegacyIngestKey()
    }

    fun observe(): StateFlow<AppSettings> = state.asStateFlow()
    fun current(): AppSettings = read()

    fun updatePrimaryUrl(value: String) = update(read().copy(primaryUrl = value.trim()))
    fun updateBackupUrl(value: String) = update(read().copy(backupUrl = value.trim()))
    fun updateHermesMfpSyncTriggerUrl(value: String) = update(read().copy(hermesMfpSyncTriggerUrl = value.trim()))
    fun updateIngestKey(value: String) {
        secretStore.writeIngestKey(value)
        state.value = read()
    }
    fun setNutritionSyncEnabled(value: Boolean) = update(read().copy(nutritionSyncEnabled = value))
    fun setMyFitnessPalAssistEnabled(value: Boolean) = update(read().copy(myFitnessPalAssistEnabled = value))
    fun setDexcomWriteEnabled(value: Boolean) = update(read().copy(dexcomWriteEnabled = value))
    fun setLogRetentionDays(value: Int) = update(read().copy(logRetentionDays = value))

    private fun read(): AppSettings = AppSettings(
        primaryUrl = prefs.getString("primaryUrl", AppSettings().primaryUrl) ?: AppSettings().primaryUrl,
        backupUrl = prefs.getString("backupUrl", AppSettings().backupUrl) ?: AppSettings().backupUrl,
        hermesMfpSyncTriggerUrl = prefs.getString("hermesMfpSyncTriggerUrl", AppSettings().hermesMfpSyncTriggerUrl)
            ?: AppSettings().hermesMfpSyncTriggerUrl,
        ingestKey = secretStore.readIngestKey(),
        nutritionSyncEnabled = prefs.getBoolean("nutritionSyncEnabled", false),
        myFitnessPalAssistEnabled = prefs.getBoolean("myFitnessPalAssistEnabled", false),
        dexcomWriteEnabled = prefs.getBoolean("dexcom_write_enabled", false),
        logRetentionDays = prefs.getInt("logRetentionDays", 30),
    )

    private fun update(settings: AppSettings) {
        prefs.edit()
            .putString("primaryUrl", settings.primaryUrl)
            .putString("backupUrl", settings.backupUrl)
            .putString("hermesMfpSyncTriggerUrl", settings.hermesMfpSyncTriggerUrl)
            .putBoolean("nutritionSyncEnabled", settings.nutritionSyncEnabled)
            .putBoolean("myFitnessPalAssistEnabled", settings.myFitnessPalAssistEnabled)
            .putBoolean("dexcom_write_enabled", settings.dexcomWriteEnabled)
            .putInt("logRetentionDays", settings.logRetentionDays)
            .apply()
        state.value = settings
    }

    private fun migrateLegacyIngestKey() {
        val legacy = prefs.getString("ingestKey", "").orEmpty()
        if (legacy.isBlank() || secretStore.readIngestKey().isNotBlank()) return
        secretStore.writeIngestKey(legacy)
        prefs.edit().remove("ingestKey").apply()
        state.value = read()
    }
}
