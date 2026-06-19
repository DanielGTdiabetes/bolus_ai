package org.bolusai.companion.queue

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface MealQueueDao {
    @Query("SELECT * FROM meal_queue ORDER BY updated_at DESC LIMIT :limit")
    fun observeRecent(limit: Int = 200): Flow<List<MealQueueItem>>

    @Query("SELECT * FROM meal_queue WHERE dedupe_hash = :dedupeHash LIMIT 1")
    suspend fun findByDedupeHash(dedupeHash: String): MealQueueItem?

    @Query("SELECT * FROM meal_queue WHERE external_id = :externalId ORDER BY updated_at DESC LIMIT 1")
    suspend fun findLatestByExternalId(externalId: String): MealQueueItem?

    @Query("SELECT dedupe_hash FROM meal_queue WHERE status = 'SENT'")
    suspend fun sentDedupeHashes(): List<String>

    @Query(
        """
        SELECT * FROM meal_queue
        WHERE status IN ('QUEUED', 'FAILED', 'NEEDS_RETRY')
        AND next_retry_at <= :now
        ORDER BY created_at ASC
        LIMIT :limit
        """,
    )
    suspend fun dueForSending(now: Long, limit: Int = 25): List<MealQueueItem>

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(item: MealQueueItem): Long

    @Update
    suspend fun update(item: MealQueueItem)

    @Query("UPDATE meal_queue SET updated_at = :now WHERE dedupe_hash = :dedupeHash")
    suspend fun touch(dedupeHash: String, now: Long)

    @Query("DELETE FROM meal_queue")
    suspend fun clear()
}
