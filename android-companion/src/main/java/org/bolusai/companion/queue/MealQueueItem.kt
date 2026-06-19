package org.bolusai.companion.queue

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "meal_queue",
    indices = [
        Index(value = ["dedupe_hash"], unique = true),
        Index(value = ["external_id"]),
        Index(value = ["status"]),
        Index(value = ["next_retry_at"]),
    ],
)
data class MealQueueItem(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    @ColumnInfo(name = "external_id")
    val externalId: String,
    @ColumnInfo(name = "dedupe_hash")
    val dedupeHash: String,
    @ColumnInfo(name = "payload_json")
    val payloadJson: String,
    val status: MealQueueStatus,
    @ColumnInfo(name = "attempt_count")
    val attemptCount: Int = 0,
    @ColumnInfo(name = "last_error")
    val lastError: String? = null,
    @ColumnInfo(name = "endpoint_used")
    val endpointUsed: String? = null,
    @ColumnInfo(name = "backend_response")
    val backendResponse: String? = null,
    @ColumnInfo(name = "created_at")
    val createdAt: Long,
    @ColumnInfo(name = "updated_at")
    val updatedAt: Long,
    @ColumnInfo(name = "next_retry_at")
    val nextRetryAt: Long,
    @ColumnInfo(name = "metadata_id")
    val metadataId: String,
    @ColumnInfo(name = "source_package")
    val sourcePackage: String,
    @ColumnInfo(name = "start_time")
    val startTime: String,
    @ColumnInfo(name = "end_time")
    val endTime: String,
    @ColumnInfo(name = "meal_type")
    val mealType: String?,
    @ColumnInfo(name = "carbohydrates_g")
    val carbohydratesGrams: Double?,
    @ColumnInfo(name = "protein_g")
    val proteinGrams: Double?,
    @ColumnInfo(name = "fat_g")
    val fatGrams: Double?,
    @ColumnInfo(name = "fiber_g")
    val fiberGrams: Double?,
    @ColumnInfo(name = "calories_kcal")
    val caloriesKcal: Double?,
)
