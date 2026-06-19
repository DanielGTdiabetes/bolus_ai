package org.bolusai.companion.queue

import org.bolusai.companion.health.sampleRecord
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MealQueueRepositoryTest {
    @Test
    fun queueItemContainsRequiredPersistentFields() {
        val item = sampleRecord().toQueueItem(
            status = MealQueueStatus.QUEUED,
            nowMillis = 1_000L,
            payloadJson = "{\"data\":{}}",
        )

        assertEquals("mfp-1", item.externalId)
        assertEquals(sampleRecord().dedupeHash, item.dedupeHash)
        assertEquals(MealQueueStatus.QUEUED, item.status)
        assertEquals(0, item.attemptCount)
        assertEquals(1_000L, item.nextRetryAt)
        assertTrue(item.payloadJson.contains("data"))
    }

    @Test
    fun retryBackoffMovesThroughExpectedDelays() {
        assertEquals(60_000L, retryDelayMillis(1))
        assertEquals(300_000L, retryDelayMillis(2))
        assertEquals(900_000L, retryDelayMillis(3))
        assertEquals(1_800_000L, retryDelayMillis(4))
        assertEquals(3_600_000L, retryDelayMillis(8))
    }
}
