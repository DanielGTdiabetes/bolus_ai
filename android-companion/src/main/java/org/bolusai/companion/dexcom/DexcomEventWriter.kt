package org.bolusai.companion.dexcom

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.util.Log

object DexcomEventWriter {
    private const val TAG = "BolusAI-DexcomBridge"
    private const val ACTION_ADD_INSULIN_EVENT = "com.bolusai.ADD_INSULIN_EVENT"
    private const val ACTION_ADD_MEAL_EVENT = "com.bolusai.ADD_MEAL_EVENT"
    private const val ACTION_ADD_EXERCISE_EVENT = "com.bolusai.ADD_EXERCISE_EVENT"
    private const val ACTION_ADD_NOTE_EVENT = "com.bolusai.ADD_NOTE_EVENT"
    private const val DEXCOM_PACKAGE = "com.dexcom.g7"
    private const val DEXCOM_RECEIVER = "com.bolusai.EventInjectorReceiver"

    private fun dexcomIntent(action: String): Intent =
        Intent().apply {
            setClassName(DEXCOM_PACKAGE, DEXCOM_RECEIVER)
            setAction(action)
        }

    private fun Intent.putLatestGlucose(context: Context) {
        GlucoseQueueRepository(context).latest(MAX_GLUCOSE_AGE_MS)?.let {
            putExtra("glucose", it.glucoseMgdl)
        }
    }

    fun isReceiverAvailable(context: Context): Boolean {
        val intent = dexcomIntent(ACTION_ADD_INSULIN_EVENT)
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
            val intent = dexcomIntent(ACTION_ADD_INSULIN_EVENT).apply {
                putExtra("insulinType", insulinType)
                putExtra("insulinUnits", insulinUnits)
                putExtra("timestamp", timestamp)
                putLatestGlucose(context)
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
            val intent = dexcomIntent(ACTION_ADD_MEAL_EVENT).apply {
                putExtra("carbs", carbsGrams)
                putExtra("timestamp", timestamp)
                putLatestGlucose(context)
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

    fun sendExerciseEvent(
        context: Context,
        durationMinutes: Int,
        intensity: String? = null,
        timestamp: Long = System.currentTimeMillis(),
    ): Boolean {
        if (durationMinutes <= 0) {
            Log.e(TAG, "invalid exercise duration=$durationMinutes")
            return false
        }

        return try {
            val intent = dexcomIntent(ACTION_ADD_EXERCISE_EVENT).apply {
                putExtra("duration", durationMinutes)
                intensity?.takeIf { it.isNotBlank() }?.let { putExtra("intensity", it) }
                putExtra("timestamp", timestamp)
                putLatestGlucose(context)
            }
            context.sendBroadcast(intent)
            Log.i(TAG, "exercise event sent to Dexcom")
            true
        } catch (error: Exception) {
            Log.e(TAG, "failed to send exercise event to Dexcom", error)
            false
        }
    }

    fun sendNoteEvent(
        context: Context,
        note: String,
        timestamp: Long = System.currentTimeMillis(),
    ): Boolean {
        if (note.isBlank()) {
            Log.e(TAG, "empty note")
            return false
        }

        return try {
            val intent = dexcomIntent(ACTION_ADD_NOTE_EVENT).apply {
                putExtra("note", note)
                putExtra("timestamp", timestamp)
                putLatestGlucose(context)
            }
            context.sendBroadcast(intent)
            Log.i(TAG, "note event sent to Dexcom")
            true
        } catch (error: Exception) {
            Log.e(TAG, "failed to send note event to Dexcom", error)
            false
        }
    }

    private const val MAX_GLUCOSE_AGE_MS = 15 * 60_000L
}
