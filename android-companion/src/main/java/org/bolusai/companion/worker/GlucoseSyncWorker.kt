package org.bolusai.companion.worker

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.dexcom.GlucoseQueueRepository
import org.bolusai.companion.dexcom.GlucoseReading
import org.bolusai.companion.dexcom.GlucoseSyncDiagnosticsRepository
import org.bolusai.companion.network.ActiveEndpoint
import org.bolusai.companion.network.GlucoseIngestClient
import org.bolusai.companion.network.GlucoseIngestResult

class GlucoseSyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val settings = AppSettingsRepository(applicationContext).current()
        val queue = GlucoseQueueRepository(applicationContext)
        val diagnostics = GlucoseSyncDiagnosticsRepository(applicationContext)
        if (!settings.dexcomGlucoseSyncEnabled) return Result.success()
        val glucoseIngestKey = settings.glucoseIngestKey.ifBlank { settings.ingestKey }
        if (glucoseIngestKey.isBlank()) {
            diagnostics.recordUploadFailure(null, "Missing ingest key", queue.pending().size)
            return Result.failure()
        }

        val recoveryReason = inputData.getString(GlucoseSyncScheduler.RECOVERY_REASON_KEY)
        if (!recoveryReason.isNullOrBlank()) {
            diagnostics.recordRecovery(
                previousWorkId = "backoff",
                replacementWorkId = id.toString(),
                reason = recoveryReason,
            )
        }
        val drain = GlucoseQueueDrainer(
            pending = queue::pending,
            send = { reading ->
                GlucoseIngestClient().send(
                    primaryUrl = settings.primaryUrl,
                    backupUrl = settings.backupUrl,
                    ingestKey = glucoseIngestKey,
                    reading = reading,
                )
            },
            acknowledge = queue::markSent,
            onAttempt = diagnostics::recordUploadAttempt,
            onFailure = diagnostics::recordUploadFailure,
            onSuccess = diagnostics::recordUploadSuccess,
        ).drain(requirePrimaryAcknowledgement = settings.primaryUrl.isNotBlank())
        if (drain.outcome == GlucoseDrainOutcome.RETRY) {
            diagnostics.recordWorkerRetry(
                workId = id.toString(),
                runAttemptCount = runAttemptCount + 1,
                reason = drain.reason.orEmpty(),
            )
        }
        return when (drain.outcome) {
            GlucoseDrainOutcome.SUCCESS -> Result.success()
            GlucoseDrainOutcome.RETRY -> Result.retry()
            GlucoseDrainOutcome.FAILURE -> Result.failure()
        }
    }
}

internal enum class GlucoseDrainOutcome {
    SUCCESS,
    RETRY,
    FAILURE,
}

internal data class GlucoseDrainResult(
    val outcome: GlucoseDrainOutcome,
    val reason: String? = null,
)

internal class GlucoseQueueDrainer(
    private val pending: () -> List<GlucoseReading>,
    private val send: suspend (GlucoseReading) -> GlucoseIngestResult,
    private val acknowledge: (GlucoseReading) -> Unit,
    private val onAttempt: (Int) -> Unit = {},
    private val onFailure: (Int?, String, Int) -> Unit = { _, _, _ -> },
    private val onSuccess: (ActiveEndpoint, Int?, Int, String) -> Unit = { _, _, _, _ -> },
) {
    suspend fun drain(requirePrimaryAcknowledgement: Boolean): GlucoseDrainResult {
        while (true) {
            val queued = pending()
            val reading = queued.firstOrNull()
                ?: return GlucoseDrainResult(GlucoseDrainOutcome.SUCCESS)
            onAttempt(queued.size)
            val result = send(reading)
            if (!result.ok) {
                onFailure(result.statusCode, result.body, queued.size)
                return if (GlucoseSyncResultPolicy.shouldRetry(result.statusCode)) {
                    GlucoseDrainResult(GlucoseDrainOutcome.RETRY, "transient_upload_failure")
                } else {
                    GlucoseDrainResult(GlucoseDrainOutcome.FAILURE, "terminal_upload_failure")
                }
            }
            if (result.endpoint == ActiveEndpoint.BACKUP && requirePrimaryAcknowledgement) {
                // The persistent queue remains authoritative until the NAS
                // acknowledges this reading. Backend reading_uid makes replay safe.
                onSuccess(result.endpoint, result.statusCode, queued.size, result.body)
                return GlucoseDrainResult(GlucoseDrainOutcome.RETRY, "primary_ack_pending")
            }
            acknowledge(reading)
            onSuccess(result.endpoint, result.statusCode, pending().size, result.body)
        }
    }
}

internal object GlucoseSyncResultPolicy {
    fun shouldRetry(statusCode: Int?): Boolean =
        statusCode == null || statusCode == 408 || statusCode == 429 || statusCode >= 500
}
