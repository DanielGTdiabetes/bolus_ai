package org.bolusai.companion.security

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class SecretStore(context: Context) {
    private val appContext = context.applicationContext
    private val masterKey = MasterKey.Builder(appContext)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()
    private val preferences = EncryptedSharedPreferences.create(
        appContext,
        FILE_NAME,
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun readIngestKey(): String = preferences.getString(KEY_INGEST, "").orEmpty()

    fun writeIngestKey(value: String) {
        preferences.edit().putString(KEY_INGEST, value.trim()).apply()
    }

    private companion object {
        const val FILE_NAME = "bolus_companion_secrets"
        const val KEY_INGEST = "nutrition_ingest_key"
    }
}
