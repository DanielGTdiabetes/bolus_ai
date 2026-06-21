package org.bolusai.companion.queue

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext
import org.bolusai.companion.diagnostics.Sanitizer
import org.bolusai.companion.health.AutoExportPayloadBuilder
import org.bolusai.companion.health.NutritionRecordSnapshot
import org.bolusai.companion.network.ActiveEndpoint
import org.bolusai.companion.network.NutritionIngestResult
import java.time.Instant

class MealQueueRepository(context: Context) {
    private val dao = BolusCompanionDatabase.get(context).mealQueueDao()
    private val payloadBuilder = AutoExportPayloadBuilder()

    fun observeRecent(): Flow<List<MealQueueItem>> = dao.observeRecent()

    suspend fun sentDedupeHashes(): Set<String> = withContext(Dispatchers.IO) {
        dao.sentDedupeHashes().toSet()
    }

    suspend fun findByDedupeHash(dedupeHash: String): MealQueueItem? = withContext(Dispatchers.IO) {
        dao.findByDedupeHash(dedupeHash)
    }

    suspend fun enqueueDetected(records: List<NutritionRecordSnapshot>, now: Instant = Instant.now()): EnqueueSummary =
        withContext(Dispatchers.IO) {
            val epoch = now.toEpochMilli()
            val queuedHashes = mutableSetOf<String>()
            val duplicateHashes = mutableSetOf<String>()
            val updateHashes = mutableSetOf<String>()

            records.distinctBy { it.dedupeHash }.forEach { record ->
                val existing = dao.findByDedupeHash(record.dedupeHash)
                if (existing != null) {
                    dao.touch(record.dedupeHash, epoch)
                    duplicateHashes += record.dedupeHash
                    return@forEach
                }

                val externalId = record.externalId()
                val previousSameExternal = dao.findLatestByExternalId(externalId)
                val status = if (previousSameExternal != null && previousSameExternal.dedupeHash != record.dedupeHash) {
                    updateHashes += record.dedupeHash
                    MealQueueStatus.UPDATE_DETECTED
                } else {
                    queuedHashes += record.dedupeHash
                    MealQueueStatus.QUEUED
                }
                dao.insert(record.toQueueItem(status = status, nowMillis = epoch, payloadJson = payloadBuilder.build(listOf(record))))
            }

            EnqueueSummary(
                queuedHashes = queuedHashes,
                duplicateHashes = duplicateHashes,
                updateHashes = updateHashes,
            )
        }

    suspend fun dueForSending(now: Instant = Instant.now(), limit: Int = 25): List<MealQueueItem> =
        withContext(Dispatchers.IO) {
            dao.dueForSending(now.toEpochMilli(), limit)
        }

    suspend fun markSending(items: List<MealQueueItem>, now: Instant = Instant.now()) = withContext(Dispatchers.IO) {
        val epoch = now.toEpochMilli()
        items.forEach { dao.update(it.copy(status = MealQueueStatus.SENDING, updatedAt = epoch)) }
    }

    suspend fun markSent(items: List<MealQueueItem>, result: NutritionIngestResult, now: Instant = Instant.now()) =
        withContext(Dispatchers.IO) {
            val epoch = now.toEpochMilli()
            val response = Sanitizer.sanitize("HTTP ${result.statusCode ?: "-"} ${result.body}")
            items.forEach {
                dao.update(
                    it.copy(
                        status = MealQueueStatus.SENT,
                        endpointUsed = result.endpoint.name.lowercase(),
                        backendResponse = response,
                        lastError = null,
                        updatedAt = epoch,
                        nextRetryAt = epoch,
                    ),
                )
            }
        }

    suspend fun markRetry(items: List<MealQueueItem>, result: NutritionIngestResult, now: Instant = Instant.now()) =
        withContext(Dispatchers.IO) {
            val epoch = now.toEpochMilli()
            val error = Sanitizer.sanitize(result.body)
            items.forEach {
                val attempts = it.attemptCount + 1
                dao.update(
                    it.copy(
                        status = if (attempts >= 8) MealQueueStatus.FAILED else MealQueueStatus.NEEDS_RETRY,
                        attemptCount = attempts,
                        lastError = error,
                        endpointUsed = result.endpoint.takeIf { endpoint -> endpoint != ActiveEndpoint.NONE }?.name?.lowercase(),
                        backendResponse = Sanitizer.sanitize("HTTP ${result.statusCode ?: "-"} ${result.body}"),
                        updatedAt = epoch,
                        nextRetryAt = epoch + retryDelayMillis(attempts),
                    ),
                )
            }
        }

    suspend fun requeueFailed(now: Instant = Instant.now()) = withContext(Dispatchers.IO) {
        val epoch = now.toEpochMilli()
        dao.dueForSending(Long.MAX_VALUE, 200)
            .filter { it.status == MealQueueStatus.FAILED || it.status == MealQueueStatus.NEEDS_RETRY }
            .forEach { dao.update(it.copy(status = MealQueueStatus.QUEUED, nextRetryAt = epoch, updatedAt = epoch)) }
    }

    suspend fun clear() = withContext(Dispatchers.IO) { dao.clear() }
}

data class EnqueueSummary(
    val queuedHashes: Set<String>,
    val duplicateHashes: Set<String>,
    val updateHashes: Set<String>,
) {
    val queued: Int = queuedHashes.size
    val duplicates: Int = duplicateHashes.size
    val updates: Int = updateHashes.size
}

fun NutritionRecordSnapshot.externalId(): String =
    metadataId.ifBlank { "$sourcePackage|${startTime}|${endTime}|${mealType.orEmpty()}" }

fun NutritionRecordSnapshot.toQueueItem(
    status: MealQueueStatus,
    nowMillis: Long,
    payloadJson: String,
): MealQueueItem = MealQueueItem(
    externalId = externalId(),
    dedupeHash = dedupeHash,
    payloadJson = payloadJson,
    status = status,
    createdAt = nowMillis,
    updatedAt = nowMillis,
    nextRetryAt = nowMillis,
    metadataId = metadataId,
    sourcePackage = sourcePackage,
    startTime = startTime.toString(),
    endTime = endTime.toString(),
    mealType = mealType,
    carbohydratesGrams = carbohydratesGrams,
    proteinGrams = proteinGrams,
    fatGrams = fatGrams,
    fiberGrams = fiberGrams,
    caloriesKcal = caloriesKcal,
)

fun MealQueueItem.toRecordSnapshot(): NutritionRecordSnapshot = NutritionRecordSnapshot(
    metadataId = metadataId,
    sourcePackage = sourcePackage,
    startTime = Instant.parse(startTime),
    endTime = Instant.parse(endTime),
    mealType = mealType,
    carbohydratesGrams = carbohydratesGrams,
    proteinGrams = proteinGrams,
    fatGrams = fatGrams,
    fiberGrams = fiberGrams,
    caloriesKcal = caloriesKcal,
)

fun retryDelayMillis(attempt: Int): Long {
    val minutes = when (attempt) {
        0, 1 -> 1L
        2 -> 5L
        3 -> 15L
        4 -> 30L
        else -> 60L
    }
    return minutes * 60_000L
}
