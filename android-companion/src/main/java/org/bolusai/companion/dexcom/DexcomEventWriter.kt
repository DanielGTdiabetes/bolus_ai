package org.bolusai.companion.dexcom

import android.content.Context
import android.content.Intent
import android.util.Log

object DexcomEventWriter {
    private const val TAG = "BolusAI-DexcomBridge"
    private const val ACTION_ADD_INSULIN_EVENT = "com.bolusai.ADD_INSULIN_EVENT"
    private const val DEXCOM_PACKAGE = "com.dexcom.g7"
    private const val DEXCOM_RECEIVER = "com.bolusai.EventInjectorReceiver"

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
}
