package org.bolusai.companion.worker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.bolusai.companion.R
import org.bolusai.companion.usage.ForegroundAppWatcher
import org.bolusai.companion.usage.UsageAccess

class NutritionActiveSyncService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var syncStarted = false
    private var myFitnessPalWasForeground = false
    private var lastMyFitnessPalExitSyncAt = 0L

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }

        startForegroundServiceNotification("Revisando comidas")
        if (syncStarted) return START_STICKY
        syncStarted = true
        scope.launch { watchMyFitnessPalExit() }
        scope.launch {
            while (isActive) {
                runSync("Revision periodica")
                delay(SYNC_INTERVAL_MS)
            }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun startForegroundServiceNotification(message: String) {
        ensureNotificationChannel()
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notification(message), type)
    }

    private fun updateNotification(message: String) {
        ensureNotificationChannel()
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, notification(message))
    }

    private suspend fun watchMyFitnessPalExit() {
        val watcher = ForegroundAppWatcher(applicationContext)
        while (scope.isActive) {
            if (!UsageAccess.hasPermission(applicationContext)) {
                updateNotification("Activa Acceso de uso para detectar MyFitnessPal")
                delay(USAGE_WATCH_INTERVAL_MS)
                continue
            }

            val isMyFitnessPalForeground = watcher.currentForegroundPackage() == MYFITNESSPAL_PACKAGE
            if (myFitnessPalWasForeground && !isMyFitnessPalForeground) {
                val now = System.currentTimeMillis()
                if (now - lastMyFitnessPalExitSyncAt > MYFITNESSPAL_EXIT_COOLDOWN_MS) {
                    lastMyFitnessPalExitSyncAt = now
                    updateNotification("MyFitnessPal cerrado, esperando datos")
                    delay(MYFITNESSPAL_WRITE_DELAY_MS)
                    runSync("Salida de MyFitnessPal")
                }
            }
            myFitnessPalWasForeground = isMyFitnessPalForeground
            delay(USAGE_WATCH_INTERVAL_MS)
        }
    }

    private suspend fun runSync(prefix: String) {
        runCatching {
            val result = NutritionSyncRunner(applicationContext).run()
            if (result.message == "Sync off") {
                stopSelf()
                return
            }
            updateNotification("$prefix: ${result.message}")
        }.onFailure {
            updateNotification("Error revisando comidas")
        }
    }

    private fun notification(message: String) = NotificationCompat.Builder(this, CHANNEL_ID)
        .setSmallIcon(R.drawable.ic_launcher)
        .setContentTitle("Bolus AI Companion")
        .setContentText(message)
        .setOngoing(true)
        .setOnlyAlertOnce(true)
        .setPriority(NotificationCompat.PRIORITY_LOW)
        .build()

    private fun ensureNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "Bolus AI nutrition sync",
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
    }

    companion object {
        private const val ACTION_STOP = "org.bolusai.companion.action.STOP_ACTIVE_SYNC"
        private const val CHANNEL_ID = "nutrition_active_sync"
        private const val NOTIFICATION_ID = 2001
        private const val SYNC_INTERVAL_MS = 60_000L
        private const val USAGE_WATCH_INTERVAL_MS = 5_000L
        private const val MYFITNESSPAL_WRITE_DELAY_MS = 20_000L
        private const val MYFITNESSPAL_EXIT_COOLDOWN_MS = 90_000L
        private const val MYFITNESSPAL_PACKAGE = "com.myfitnesspal.android"

        fun start(context: Context) {
            val intent = Intent(context, NutritionActiveSyncService::class.java)
            androidx.core.content.ContextCompat.startForegroundService(context, intent)
        }

        fun stop(context: Context) {
            val intent = Intent(context, NutritionActiveSyncService::class.java).setAction(ACTION_STOP)
            context.startService(intent)
        }
    }
}
