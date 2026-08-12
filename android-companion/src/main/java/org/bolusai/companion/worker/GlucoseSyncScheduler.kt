package org.bolusai.companion.worker

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.workDataOf
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import org.bolusai.companion.dexcom.GlucoseSyncDiagnosticsRepository
import java.util.concurrent.TimeUnit

object GlucoseSyncScheduler {
    private const val WORK_NAME = "bolus_ai_dexcom_glucose_sync"
    private const val RUNNING_OBSERVATION_TIMEOUT_MS = 90_000L
    internal const val RECOVERY_REASON_KEY = "glucose_sync_recovery_reason"
    private const val RECOVERY_NEW_READING = "new_reading_woke_backoff"
    private val schedulerScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val wakeMutex = Mutex()

    fun syncNow(context: Context) {
        val appContext = context.applicationContext
        val workManager = WorkManager.getInstance(appContext)
        val request = buildRequest()
        // Persist an eligible unique request before doing any asynchronous
        // inspection. KEEP is safe when a worker is already RUNNING.
        workManager.enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.KEEP, request)
        GlucoseSyncDiagnosticsRepository(appContext).recordWorkState(
            workId = request.id.toString(),
            state = "requested",
            runAttemptCount = 0,
            nextEligibilityMillis = null,
            action = "enqueue_keep",
        )
        schedulerScope.launch {
            wakeMutex.withLock {
                inspectAndWakeIfNeeded(appContext, workManager)
            }
        }
    }

    private fun buildRequest(recoveryReason: String? = null) =
        OneTimeWorkRequestBuilder<GlucoseSyncWorker>()
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .apply {
                if (recoveryReason != null) {
                    setInputData(workDataOf(RECOVERY_REASON_KEY to recoveryReason))
                }
            }
            .build()

    private suspend fun inspectAndWakeIfNeeded(context: Context, workManager: WorkManager) {
        val diagnostics = GlucoseSyncDiagnosticsRepository(context)
        var snapshots = workManager.getWorkInfosForUniqueWorkFlow(WORK_NAME).first().toSnapshots()
        if (GlucoseSyncWakePolicy.decide(snapshots, System.currentTimeMillis()) ==
            GlucoseSyncWakeDecision.PRESERVE_RUNNING
        ) {
            snapshots.forEach { diagnostics.recordWorkSnapshot(it, "preserve_running") }
            val settledSnapshots = withTimeoutOrNull(RUNNING_OBSERVATION_TIMEOUT_MS) {
                workManager.getWorkInfosForUniqueWorkFlow(WORK_NAME)
                    .first { infos -> infos.none { it.state == WorkInfo.State.RUNNING } }
                    .toSnapshots()
            }
            if (settledSnapshots == null) {
                snapshots.forEach { diagnostics.recordWorkSnapshot(it, "running_observation_timeout") }
                return
            }
            snapshots = settledSnapshots
        }

        when (GlucoseSyncWakePolicy.decide(snapshots, System.currentTimeMillis())) {
            GlucoseSyncWakeDecision.WAKE_BACKOFF -> {
                val previous = snapshots.first {
                    it.state == WorkInfo.State.ENQUEUED && it.runAttemptCount > 0
                }
                val replacement = buildRequest(RECOVERY_NEW_READING)
                diagnostics.recordWorkSnapshot(previous, "replace_backoff")
                diagnostics.recordRecovery(
                    previousWorkId = previous.workId,
                    replacementWorkId = replacement.id.toString(),
                    reason = RECOVERY_NEW_READING,
                )
                workManager.enqueueUniqueWork(
                    WORK_NAME,
                    ExistingWorkPolicy.REPLACE,
                    replacement,
                )
            }

            GlucoseSyncWakeDecision.ENSURE_SCHEDULED -> {
                val request = buildRequest()
                diagnostics.recordWorkState(
                    workId = request.id.toString(),
                    state = "requested",
                    runAttemptCount = 0,
                    nextEligibilityMillis = null,
                    action = "enqueue_after_running_finished",
                )
                workManager.enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.KEEP, request)
            }

            GlucoseSyncWakeDecision.KEEP_ENQUEUED ->
                snapshots.forEach { diagnostics.recordWorkSnapshot(it, "keep_enqueued") }

            GlucoseSyncWakeDecision.PRESERVE_RUNNING ->
                snapshots.forEach { diagnostics.recordWorkSnapshot(it, "preserve_running") }
        }
    }
}

internal data class GlucoseWorkSnapshot(
    val workId: String,
    val state: WorkInfo.State,
    val runAttemptCount: Int,
    val nextScheduleTimeMillis: Long,
)

internal enum class GlucoseSyncWakeDecision {
    ENSURE_SCHEDULED,
    PRESERVE_RUNNING,
    WAKE_BACKOFF,
    KEEP_ENQUEUED,
}

internal object GlucoseSyncWakePolicy {
    fun decide(
        work: List<GlucoseWorkSnapshot>,
        nowMillis: Long,
    ): GlucoseSyncWakeDecision {
        val unfinished = work.filterNot { it.state.isFinished }
        if (unfinished.isEmpty()) return GlucoseSyncWakeDecision.ENSURE_SCHEDULED
        if (unfinished.any { it.state == WorkInfo.State.RUNNING }) {
            return GlucoseSyncWakeDecision.PRESERVE_RUNNING
        }
        if (
            unfinished.any {
                it.state == WorkInfo.State.ENQUEUED &&
                    it.runAttemptCount > 0 &&
                    it.nextScheduleTimeMillis > nowMillis
            }
        ) {
            return GlucoseSyncWakeDecision.WAKE_BACKOFF
        }
        return GlucoseSyncWakeDecision.KEEP_ENQUEUED
    }
}

private fun List<WorkInfo>.toSnapshots(): List<GlucoseWorkSnapshot> = map {
    GlucoseWorkSnapshot(
        workId = it.id.toString(),
        state = it.state,
        runAttemptCount = it.runAttemptCount,
        nextScheduleTimeMillis = it.nextScheduleTimeMillis,
    )
}

private fun GlucoseSyncDiagnosticsRepository.recordWorkSnapshot(
    snapshot: GlucoseWorkSnapshot,
    action: String,
) = recordWorkState(
    workId = snapshot.workId,
    state = snapshot.state.name.lowercase(),
    runAttemptCount = snapshot.runAttemptCount,
    nextEligibilityMillis = snapshot.nextScheduleTimeMillis,
    action = action,
)
