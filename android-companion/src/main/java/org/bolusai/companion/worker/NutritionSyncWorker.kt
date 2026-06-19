package org.bolusai.companion.worker

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

class NutritionSyncWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        return runCatching {
            if (NutritionSyncRunner(applicationContext).run().retryable) Result.retry() else Result.success()
        }.getOrElse {
            Result.retry()
        }
    }
}
