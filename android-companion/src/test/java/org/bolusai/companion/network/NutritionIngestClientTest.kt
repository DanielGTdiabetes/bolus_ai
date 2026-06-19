package org.bolusai.companion.network

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NutritionIngestClientTest {
    @Test
    fun usesBackupWhenPrimaryFails() = runBlocking {
        val client = NutritionIngestClient { _, _, _, endpoint ->
            when (endpoint) {
                ActiveEndpoint.PRIMARY -> NutritionIngestResult(false, endpoint, null, "timeout")
                ActiveEndpoint.BACKUP -> NutritionIngestResult(true, endpoint, 200, "{}")
                ActiveEndpoint.NONE -> error("not used")
            }
        }

        val result = client.send("https://primary", "https://backup", "key", "{}")

        assertTrue(result.ok)
        assertEquals(ActiveEndpoint.BACKUP, result.endpoint)
    }

    @Test
    fun leavesPayloadQueuedWhenBothEndpointsFail() = runBlocking {
        val client = NutritionIngestClient { _, _, _, endpoint ->
            NutritionIngestResult(false, endpoint, 503, "down")
        }

        val result = client.send("https://primary", "https://backup", "key", "{}")

        assertEquals(false, result.ok)
        assertEquals(ActiveEndpoint.NONE, result.endpoint)
        assertTrue(result.body.contains("Principal"))
        assertTrue(result.body.contains("Backup"))
    }
}
