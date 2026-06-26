package org.bolusai.companion.dexcom

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.util.Log

object DexcomEventWriter {
    private const val TAG = "BolusAI-DexcomBridge"
    private const val ACTION_ADD_INSULIN_EVENT = "com.bolusai.ADD_INSULIN_EVENT"
    private const val ACTION_ADD_MEAL_EVENT = "com.bolusai.ADD_MEAL_EVENT"
    private const val DEXCOM_PACKAGE = "com.dexcom.g7"
    private const val DEXCOM_RECEIVER = "com.bolusai.EventInjectorReceiver"

    fun isReceiverAvailable(context: Context): Boolean {
        val intent = Intent(ACTION_ADD_INSULIN_EVENT).apply {
            setClassName(DEXCOM_PACKAGE, DEXCOM_RECEIVER)
        }
        return context.packageManager
            .queryBroadcastReceivers(intent, PackageManager.MATCH_DEFAULT_ONLY)
            .isNotEmpty()
    }

    fun sendInsulinEvent(
        context: Context,
        insulinUnits: Double,
        insulinType: String = "FAST_ACTING",
        timestamp: Long = System.currentTimeMillis(),
    ): Boolean {
        if (!insulinUnits.isFinite() || insulinUnits <= 0.0) {
            Log.e(TAG, "invalid insulin units=$insulinUnits")
            return false
        }

        return try {
            val intent = Intent(ACTION_ADD_INSULIN_EVENT).apply {
                setClassName(DEXCOM_PACKAGE, DEXCOM_RECEIVER)
                putExtra("insulinType", insulinType)
                putExtra("insulinUnits", insulinUnits)
                putExtra("timestamp", timestamp)
            }
            context.sendBroadcast(intent)
            Log.i(TAG, "insulin event sent to Dexcom")
            Log.i(TAG, "units=$insulinUnits")
            Log.i(TAG, "timestamp=$timestamp")
            true
        } catch (error: Exception) {
            Log.e(TAG, "failed to send insulin event to Dexcom", error)
            false
        }
    }

    fun sendCarbsEvent(
        context: Context,
        carbsGrams: Int,
        timestamp: Long = System.currentTimeMillis(),
    ): Boolean {
        if (carbsGrams <= 0) {
            Log.e(TAG, "invalid carbs grams=$carbsGrams")
            return false
        }

        return try {
            val syncRepository = DexcomEventSyncRepository(context)
            if (syncRepository.hasRecentCarbsBroadcast(carbsGrams, timestamp)) {
                Log.i(TAG, "duplicate carbohydrate event skipped for Dexcom")
                Log.i(TAG, "carbs=$carbsGrams timestamp=$timestamp")
                return true
            }
            val intent = Intent(ACTION_ADD_MEAL_EVENT).apply {
                setClassName(DEXCOM_PACKAGE, DEXCOM_RECEIVER)
                putExtra("carbs", carbsGrams)
                putExtra("timestamp", timestamp)
            }
            context.sendBroadcast(intent)
            syncRepository.markCarbsBroadcast(carbsGrams, timestamp)
            Log.i(TAG, "carbohydrate event sent to Dexcom")
            true
        } catch (error: Exception) {
            Log.e(TAG, "failed to send carbohydrate event to Dexcom", error)
            false
        }
    }
}
