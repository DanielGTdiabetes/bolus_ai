package org.bolusai.companion.worker

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.diagnostics.HealthConnectLogRepository
import org.bolusai.companion.diagnostics.HealthConnectLogStatus
import org.bolusai.companion.health.AutoExportPayloadBuilder
import org.bolusai.companion.health.HealthConnectAvailability
import org.bolusai.companion.health.HealthConnectState
import org.bolusai.companion.health.HealthPermissions
import org.bolusai.companion.health.NutritionChangeTracker
import org.bolusai.companion.health.NutritionRecordReader
import org.bolusai.companion.network.NutritionIngestClient
import org.bolusai.companion.queue.MealQueueRepository
import org.bolusai.companion.queue.toRecordSnapshot

data class NutritionSyncRunResult(
    val retryable: Boolean,
    val message: String,
)

class NutritionSyncRunner(private val context: Context) {
    suspend fun run(includeMyFitnessPalRecords: Boolean = true): NutritionSyncRunResult {
        val settings = AppSettingsRepository(context).current()
        if (!settings.nutritionSyncEnabled) {
            return NutritionSyncRunResult(retryable = false, message = "Sync off")
        }
        if (settings.ingestKey.isBlank()) {
            return NutritionSyncRunResult(retryable = false, message = "Missing ingest key")
        }
        if (HealthConnectAvailability(context).status() != HealthConnectState.AVAILABLE) {
            return NutritionSyncRunResult(retryable = false, message = "Health Connect unavailable")
        }

        val grantedPermissions = HealthConnectClient
            .getOrCreate(context)
            .permissionController
            .getGrantedPermissions()
        if (!grantedPermissions.containsAll(HealthPermissions.readPermissionsForRequest())) {
            return NutritionSyncRunResult(retryable = false, message = "Missing Health Connect permissions")
        }

        val logRepository = HealthConnectLogRepository(context)
        val queueRepository = MealQueueRepository(context)
        val sentHashes = queueRepository.sentDedupeHashes()
        val hasHealthConnectChanges = NutritionChangeTracker(context).hasChanges()
        val observedRecords = if (hasHealthConnectChanges) {
            NutritionRecordReader(context)
                .readLatest(syncEnabled = true)
                .distinctBy { it.dedupeHash }
        } else {
            emptyList()
        }
        val eligibleRecords = if (includeMyFitnessPalRecords) {
            observedRecords
        } else {
            observedRecords.filterNot { it.sourcePackage == MYFITNESSPAL_PACKAGE }
        }
        val newRecords = eligibleRecords.filterNot { it.dedupeHash in sentHashes }
        val enqueueSummary = queueRepository.enqueueDetected(newRecords)
        newRecords.forEach { record ->
            val status = when {
                record.dedupeHash in enqueueSummary.updateHashes -> HealthConnectLogStatus.UPDATE_DETECTED
                record.dedupeHash in enqueueSummary.duplicateHashes || record.dedupeHash in sentHashes -> HealthConnectLogStatus.DUPLICATE
                else -> HealthConnectLogStatus.QUEUED
            }
            logRepository.recordDetected(record = record, status = status)
        }

        val dueItems = queueRepository.dueForSending()
            .filter { includeMyFitnessPalRecords || it.sourcePackage != MYFITNESSPAL_PACKAGE }
        if (dueItems.isEmpty()) {
            return NutritionSyncRunResult(
                retryable = false,
                message = when {
                    !hasHealthConnectChanges -> "No Health Connect changes"
                    observedRecords.isEmpty() -> "No meals detected"
                    eligibleRecords.isEmpty() -> "MyFitnessPal handled by Hermes"
                    enqueueSummary.duplicates > 0 -> "Duplicate meals ignored"
                    enqueueSummary.updates > 0 -> "Meal update detected; pending confirmation"
                    else -> "No queued meals due"
                },
            )
        }

        queueRepository.markSending(dueItems)
        val records = dueItems.map { it.toRecordSnapshot() }
        val sendResult = NutritionIngestClient().send(
            primaryUrl = settings.primaryUrl,
            backupUrl = settings.backupUrl,
            ingestKey = settings.ingestKey,
            payloadJson = AutoExportPayloadBuilder().build(records),
        )
        val logStatus = if (sendResult.ok) {
            HealthConnectLogStatus.SENT
        } else {
            HealthConnectLogStatus.NEEDS_RETRY
        }
        records.forEach { record ->
            logRepository.recordDetected(
                record = record,
                status = logStatus,
                endpointUsed = sendResult.endpoint.name.lowercase(),
                backendResponseSanitized = "HTTP ${sendResult.statusCode ?: "-"} ${sendResult.body}",
            )
        }

        return if (sendResult.ok) {
            queueRepository.markSent(dueItems, sendResult)
            NutritionSyncRunResult(retryable = false, message = "Sent ${records.size} meals (${sendResult.endpoint.name.lowercase()})")
        } else {
            queueRepository.markRetry(dueItems, sendResult)
            NutritionSyncRunResult(retryable = true, message = sendResult.body)
        }
    }

    private companion object {
        const val MYFITNESSPAL_PACKAGE = "com.myfitnesspal.android"
    }
}
