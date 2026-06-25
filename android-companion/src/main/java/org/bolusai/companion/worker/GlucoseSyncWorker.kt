package org.bolusai.companion.worker

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.dexcom.GlucoseQueueRepository
import org.bolusai.companion.network.GlucoseIngestClient

class GlucoseSyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val settings = AppSettingsRepository(applicationContext).current()
        if (!settings.dexcomGlucoseSyncEnabled) return Result.success()
        if (settings.ingestKey.isBlank()) return Result.failure()

        val queue = GlucoseQueueRepository(applicationContext)
        for (reading in queue.pending()) {
            val result = GlucoseIngestClient().send(
                primaryUrl = settings.primaryUrl,
                backupUrl = settings.backupUrl,
                ingestKey = settings.ingestKey,
                reading = reading,
            )
            if (!result.ok) return Result.retry()
            queue.markSent(reading)
        }
        return Result.success()
    }
}
