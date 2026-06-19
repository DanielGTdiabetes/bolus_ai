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
import org.bolusai.companion.health.PendingNutritionRepository
import org.bolusai.companion.network.NutritionIngestClient

data class NutritionSyncRunResult(
    val retryable: Boolean,
    val message: String,
)

class NutritionSyncRunner(private val context: Context) {
    suspend fun run(): NutritionSyncRunResult {
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
        val sentHashes = logRepository.sentDedupeHashes()
        val pendingRepository = PendingNutritionRepository(context)
        val hasHealthConnectChanges = NutritionChangeTracker(context).hasChanges()
        val observedRecords = if (hasHealthConnectChanges) {
            NutritionRecordReader(context)
                .readLatest(syncEnabled = true)
                .distinctBy { it.dedupeHash }
                .filterNot { it.dedupeHash in sentHashes }
        } else {
            emptyList()
        }
        val records = pendingRepository.stableRecords(
            observedRecords = observedRecords,
            sentHashes = sentHashes,
        )

        if (records.isEmpty()) {
            return NutritionSyncRunResult(
                retryable = false,
                message = when {
                    !hasHealthConnectChanges -> "No Health Connect changes"
                    observedRecords.isEmpty() -> "No new meals"
                    else -> "Waiting for stable meal data"
                },
            )
        }

        val sendResult = NutritionIngestClient().send(
            primaryUrl = settings.primaryUrl,
            backupUrl = settings.backupUrl,
            ingestKey = settings.ingestKey,
            payloadJson = AutoExportPayloadBuilder().build(records),
        )
        val logStatus = if (sendResult.ok) {
            HealthConnectLogStatus.SENT
        } else {
            HealthConnectLogStatus.ERROR
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
            pendingRepository.markSent(records)
            NutritionSyncRunResult(retryable = false, message = "Sent ${records.size} meals")
        } else {
            NutritionSyncRunResult(retryable = true, message = sendResult.body)
        }
    }
}
