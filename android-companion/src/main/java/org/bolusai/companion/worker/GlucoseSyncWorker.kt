package org.bolusai.companion.worker

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.dexcom.GlucoseQueueRepository
import org.bolusai.companion.dexcom.GlucoseSyncDiagnosticsRepository
import org.bolusai.companion.network.GlucoseIngestClient

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

        while (true) {
            val pending = queue.pending()
            val reading = pending.firstOrNull() ?: return Result.success()
            diagnostics.recordUploadAttempt(pending.size)
            val result = GlucoseIngestClient().send(
                primaryUrl = settings.primaryUrl,
                backupUrl = settings.backupUrl,
                ingestKey = glucoseIngestKey,
                reading = reading,
            )
            if (!result.ok) {
                diagnostics.recordUploadFailure(result.statusCode, result.body, pending.size)
                return if (GlucoseSyncResultPolicy.shouldRetry(result.statusCode)) {
                    Result.retry()
                } else {
                    Result.failure()
                }
            }
            if (result.endpoint == org.bolusai.companion.network.ActiveEndpoint.BACKUP && settings.primaryUrl.isNotBlank()) {
                // Keep the device-generated identity in the queue until the NAS
                // acknowledges it. Replays to Render are idempotent, and this
                // prevents Neon from becoming the only surviving copy.
                diagnostics.recordUploadSuccess(result.endpoint, result.statusCode, pending.size, result.body)
                return Result.retry()
            }
            queue.markSent(reading)
            diagnostics.recordUploadSuccess(result.endpoint, result.statusCode, queue.pending().size, result.body)
        }
    }
}

internal object GlucoseSyncResultPolicy {
    fun shouldRetry(statusCode: Int?): Boolean =
        statusCode == null || statusCode == 408 || statusCode == 429 || statusCode >= 500
}
