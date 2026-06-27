package org.bolusai.companion.worker

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
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
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.diagnostics.HealthConnectLogRepository
import org.bolusai.companion.diagnostics.HealthConnectLogStatus
import org.bolusai.companion.dexcom.DexcomEventSyncRepository
import org.bolusai.companion.dexcom.DexcomEventWriter
import org.bolusai.companion.dexcom.GlucoseReceiver
import org.bolusai.companion.network.DexcomBolusEventClient
import org.bolusai.companion.network.HermesMfpSyncTriggerClient
import org.bolusai.companion.network.HermesMfpSyncTriggerResult
import org.bolusai.companion.usage.ForegroundAppWatcher
import org.bolusai.companion.usage.UsageAccess

class NutritionActiveSyncService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var syncStarted = false
    private var myFitnessPalWasForeground = false
    private var lastMyFitnessPalExitSyncAt = 0L
    private var lastMissingUsageAccessLogAt = 0L
    private var lastUsageTransitionCheckAt = 0L
    private var dynamicGlucoseReceiver: GlucoseReceiver? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            recordDiagnostic("active_sync_stop", HealthConnectLogStatus.PENDING, "Service stop requested")
            stopSelf()
            return START_NOT_STICKY
        }

        startForegroundServiceNotification("Revisando comidas")
        registerDynamicGlucoseReceiver()
        if (syncStarted) return START_STICKY
        syncStarted = true
        recordDiagnostic("active_sync_start", HealthConnectLogStatus.PENDING, "Foreground nutrition sync started")
        scope.launch { watchMyFitnessPalExit() }
        scope.launch { syncDexcomBolusEvents() }
        scope.launch {
            while (isActive) {
                delay(BACKUP_SYNC_INTERVAL_MS)
                if (AppSettingsRepository(applicationContext).current().nutritionSyncEnabled) {
                    runSync("Revision de respaldo", includeMyFitnessPalRecords = false)
                }
            }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        recordDiagnostic("active_sync_destroy", HealthConnectLogStatus.PENDING, "Foreground nutrition sync destroyed")
        unregisterDynamicGlucoseReceiver()
        scope.cancel()
        super.onDestroy()
    }

    private fun registerDynamicGlucoseReceiver() {
        if (dynamicGlucoseReceiver != null) return
        dynamicGlucoseReceiver = GlucoseReceiver()
        val filter = IntentFilter(DEXCOM_EXTERNAL_BROADCAST_ACTION)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(dynamicGlucoseReceiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            registerReceiver(dynamicGlucoseReceiver, filter)
        }
    }

    private fun unregisterDynamicGlucoseReceiver() {
        dynamicGlucoseReceiver?.let { runCatching { unregisterReceiver(it) } }
        dynamicGlucoseReceiver = null
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
            if (!AppSettingsRepository(applicationContext).current().nutritionSyncEnabled) {
                delay(USAGE_WATCH_INTERVAL_MS)
                continue
            }
            if (!UsageAccess.hasPermission(applicationContext)) {
                updateNotification("Activa Acceso de uso para detectar MyFitnessPal")
                val now = System.currentTimeMillis()
                if (now - lastMissingUsageAccessLogAt > MISSING_USAGE_ACCESS_LOG_COOLDOWN_MS) {
                    lastMissingUsageAccessLogAt = now
                    recordDiagnostic(
                        event = "usage_access_missing",
                        status = HealthConnectLogStatus.ERROR,
                        detail = "Usage access permission is missing; MyFitnessPal exit cannot be detected",
                    )
                }
                delay(USAGE_WATCH_INTERVAL_MS)
                continue
            }

            val transitionCheckStart = if (lastUsageTransitionCheckAt == 0L) {
                System.currentTimeMillis() - USAGE_EVENT_LOOKBACK_MS
            } else {
                lastUsageTransitionCheckAt
            }
            val exitPackages = confirmedExitPackages()
            val isMyFitnessPalForeground = watcher.currentForegroundPackage() == MYFITNESSPAL_PACKAGE
            val currentForegroundPackage = watcher.currentForegroundPackage()
            val isConfirmedExitDestination = currentForegroundPackage in exitPackages
            val observedMyFitnessPalExit = watcher.observedExitSince(MYFITNESSPAL_PACKAGE, transitionCheckStart, exitPackages)
            lastUsageTransitionCheckAt = System.currentTimeMillis()
            if (!myFitnessPalWasForeground && isMyFitnessPalForeground) {
                recordDiagnostic(
                    event = "myfitnesspal_foreground",
                    status = HealthConnectLogStatus.DETECTED,
                    detail = "MyFitnessPal entered foreground",
                )
            }
            if ((myFitnessPalWasForeground && isConfirmedExitDestination) || observedMyFitnessPalExit) {
                val now = System.currentTimeMillis()
                if (now - lastMyFitnessPalExitSyncAt > MYFITNESSPAL_EXIT_COOLDOWN_MS) {
                    updateNotification("Confirmando cierre de MyFitnessPal")
                    recordDiagnostic(
                        event = "myfitnesspal_exit_candidate",
                        status = HealthConnectLogStatus.DETECTED,
                        detail = if (observedMyFitnessPalExit) {
                            "Usage event transition detected; checking that MyFitnessPal remains closed before triggering Hermes"
                        } else {
                            "Checking that MyFitnessPal remains closed before triggering Hermes"
                        },
                    )
                    if (!confirmMyFitnessPalClosed(watcher)) {
                        val current = watcher.currentForegroundPackage()
                        myFitnessPalWasForeground = current == MYFITNESSPAL_PACKAGE
                        updateNotification("MyFitnessPal sigue abierto")
                        recordDiagnostic(
                            event = "myfitnesspal_exit_cancelled",
                            status = HealthConnectLogStatus.PENDING,
                            detail = "Exit candidate cancelled because foreground is not a confirmed exit destination",
                        )
                        delay(USAGE_WATCH_INTERVAL_MS)
                        continue
                    }

                    lastMyFitnessPalExitSyncAt = System.currentTimeMillis()
                    updateNotification("MyFitnessPal cerrado, esperando datos")
                    recordDiagnostic(
                        event = "myfitnesspal_exit_confirmed",
                        status = HealthConnectLogStatus.DETECTED,
                        detail = "Confirmed closed after ${MYFITNESSPAL_EXIT_CONFIRMATION_CHECKS} checks; waiting ${MYFITNESSPAL_WRITE_DELAY_MS / 1000}s before triggering Hermes",
                    )
                    delay(MYFITNESSPAL_WRITE_DELAY_MS)
                    val hermesFirstResult = triggerHermesSync("Salida de MyFitnessPal")
                    if (hermesFirstResult == null || !hermesFirstResult.ok) {
                        recordDiagnostic(
                            event = "hermes_fallback_health_connect",
                            status = HealthConnectLogStatus.PENDING,
                            detail = "Hermes failed or is not configured; MyFitnessPal Health Connect records are suppressed",
                        )
                        runSync("Fallback Health Connect", includeMyFitnessPalRecords = false)
                    } else if (hermesFirstResult.shouldFollowUp()) {
                        recordDiagnostic(
                            event = "hermes_followup_scheduled",
                            status = HealthConnectLogStatus.PENDING,
                            detail = "First Hermes result requested follow-up in ${MYFITNESSPAL_FOLLOW_UP_DELAY_MS / 1000}s",
                        )
                        delay(MYFITNESSPAL_FOLLOW_UP_DELAY_MS)
                        triggerHermesSync("Seguimiento MyFitnessPal")
                    }
                } else {
                    recordDiagnostic(
                        event = "myfitnesspal_exit_cooldown",
                        status = HealthConnectLogStatus.DUPLICATE,
                        detail = "Exit ignored because cooldown is active",
                    )
                }
            }
            myFitnessPalWasForeground = isMyFitnessPalForeground
            delay(USAGE_WATCH_INTERVAL_MS)
        }
    }

    private suspend fun confirmMyFitnessPalClosed(watcher: ForegroundAppWatcher): Boolean {
        val exitPackages = confirmedExitPackages()
        repeat(MYFITNESSPAL_EXIT_CONFIRMATION_CHECKS) { index ->
            delay(MYFITNESSPAL_EXIT_CONFIRMATION_INTERVAL_MS)
            val currentPackage = watcher.currentForegroundPackage()
            val stillClosed = currentPackage in exitPackages
            recordDiagnostic(
                event = "myfitnesspal_exit_confirmation",
                status = if (stillClosed) HealthConnectLogStatus.DETECTED else HealthConnectLogStatus.PENDING,
                detail = "Check ${index + 1}/$MYFITNESSPAL_EXIT_CONFIRMATION_CHECKS: current=${currentPackage ?: "none"}",
            )
            if (!stillClosed) return false
        }
        return true
    }

    private fun confirmedExitPackages(): Set<String> =
        DEFAULT_EXIT_PACKAGES + applicationContext.packageName

    private suspend fun runSync(prefix: String, includeMyFitnessPalRecords: Boolean): NutritionSyncRunResult? {
        return runCatching {
            val result = NutritionSyncRunner(applicationContext).run(
                includeMyFitnessPalRecords = includeMyFitnessPalRecords,
            )
            if (result.message == "Sync off") {
                stopSelf()
                return@runCatching result
            }
            updateNotification("$prefix: ${result.message}")
            result
        }.onFailure {
            updateNotification("Error revisando comidas")
        }.getOrNull()
    }

    private suspend fun triggerHermesSync(prefix: String): HermesMfpSyncTriggerResult? {
        return runCatching {
            val settings = AppSettingsRepository(applicationContext).current()
            if (!settings.nutritionSyncEnabled) {
                recordDiagnostic(
                    event = "hermes_trigger_skipped",
                    status = HealthConnectLogStatus.ERROR,
                    detail = "$prefix: nutrition sync is disabled",
                )
                return@runCatching null
            }
            if (settings.hermesMfpSyncTriggerUrl.isBlank()) {
                recordDiagnostic(
                    event = "hermes_trigger_skipped",
                    status = HealthConnectLogStatus.ERROR,
                    detail = "$prefix: Hermes trigger URL is blank",
                )
                return@runCatching null
            }
            recordDiagnostic(
                event = "hermes_trigger_start",
                status = HealthConnectLogStatus.SENDING,
                detail = prefix,
                endpointUsed = settings.hermesMfpSyncTriggerUrl,
            )
            val result = HermesMfpSyncTriggerClient().trigger(
                baseUrl = settings.hermesMfpSyncTriggerUrl,
                ingestKey = settings.ingestKey,
            )
            updateNotification("$prefix Hermes: ${if (result.ok) "sync lanzado" else "error ${result.statusCode ?: "-"}"}")
            recordDiagnostic(
                event = "hermes_trigger_result",
                status = if (result.ok) HealthConnectLogStatus.SENT else HealthConnectLogStatus.ERROR,
                detail = "HTTP ${result.statusCode ?: "-"} ${result.body}",
                endpointUsed = settings.hermesMfpSyncTriggerUrl,
            )
            result
        }.onFailure {
            updateNotification("Error lanzando Hermes")
            recordDiagnostic(
                event = "hermes_trigger_exception",
                status = HealthConnectLogStatus.ERROR,
                detail = it.message ?: it::class.java.simpleName,
            )
        }.getOrNull()
    }

    private suspend fun syncDexcomBolusEvents() {
        val repository = DexcomEventSyncRepository(applicationContext)
        val client = DexcomBolusEventClient()
        while (scope.isActive) {
            val settings = AppSettingsRepository(applicationContext).current()
            if (!settings.dexcomWriteEnabled) {
                delay(DEXCOM_SYNC_INTERVAL_MS)
                continue
            }

            val lookbackTimestamp = System.currentTimeMillis() - DEXCOM_EVENT_LOOKBACK_MS
            val result = client.fetch(
                primaryUrl = settings.primaryUrl,
                backupUrl = settings.backupUrl,
                ingestKey = settings.ingestKey,
                afterId = null,
                afterTimestamp = lookbackTimestamp,
            )
            if (result.ok) {
                val legacyLastEventTimestamp = repository.lastEventTimestamp()
                if (!repository.hasProcessedEventIds() && legacyLastEventTimestamp != null) {
                    repository.markProcessedBatch(
                        result.events
                            .filter { it.timestamp <= legacyLastEventTimestamp }
                            .map { it.id },
                    )
                }
                for (event in result.events) {
                    if (repository.isProcessed(event.id)) continue
                    val sent = when (event.eventKind) {
                        "INSULIN" -> {
                            val units = event.insulinUnits
                            if (units == null) {
                                false
                            } else {
                                DexcomEventWriter.sendInsulinEvent(
                                    context = applicationContext,
                                    insulinUnits = units,
                                    insulinType = event.insulinType ?: "FAST_ACTING",
                                    glucoseMgdl = event.glucoseMgdl,
                                    useLatestGlucoseWhenMissing = event.insulinType == "LONG_ACTING",
                                    timestamp = event.timestamp,
                                )
                            }
                        }
                        "CARBS" -> {
                            val grams = event.carbsGrams
                            grams != null && DexcomEventWriter.sendCarbsEvent(
                                context = applicationContext,
                                carbsGrams = grams,
                                glucoseMgdl = event.glucoseMgdl,
                                timestamp = event.timestamp,
                            )
                        }
                        else -> false
                    }
                    if (!sent) break
                    repository.markProcessed(event.id, event.timestamp)
                }
            } else {
                recordDiagnostic(
                    event = "dexcom_bolus_sync_error",
                    status = HealthConnectLogStatus.ERROR,
                    detail = result.message,
                )
            }
            delay(DEXCOM_SYNC_INTERVAL_MS)
        }
    }

    private fun recordDiagnostic(
        event: String,
        status: HealthConnectLogStatus,
        detail: String? = null,
        endpointUsed: String? = null,
    ) {
        HealthConnectLogRepository(applicationContext).recordDiagnosticEvent(
            event = event,
            status = status,
            detail = detail,
            endpointUsed = endpointUsed,
        )
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
        private const val BACKUP_SYNC_INTERVAL_MS = 15 * 60_000L
        private const val USAGE_WATCH_INTERVAL_MS = 5_000L
        private const val USAGE_EVENT_LOOKBACK_MS = 30_000L
        private const val MYFITNESSPAL_EXIT_CONFIRMATION_CHECKS = 2
        private const val MYFITNESSPAL_EXIT_CONFIRMATION_INTERVAL_MS = 3_000L
        private const val MYFITNESSPAL_WRITE_DELAY_MS = 20_000L
        private const val MYFITNESSPAL_FOLLOW_UP_DELAY_MS = 75_000L
        private const val MYFITNESSPAL_EXIT_COOLDOWN_MS = 90_000L
        private const val MISSING_USAGE_ACCESS_LOG_COOLDOWN_MS = 10 * 60_000L
        private const val DEXCOM_SYNC_INTERVAL_MS = 15_000L
        private const val DEXCOM_EVENT_LOOKBACK_MS = 48 * 60 * 60_000L
        private const val DEXCOM_EXTERNAL_BROADCAST_ACTION = "com.dexcom.cgm.EXTERNAL_BROADCAST"
        private const val MYFITNESSPAL_PACKAGE = "com.myfitnesspal.android"
        private val DEFAULT_EXIT_PACKAGES = setOf(
            "com.mi.android.globallauncher",
            "com.android.launcher",
            "com.android.launcher3",
            "com.google.android.apps.nexuslauncher",
        )

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
