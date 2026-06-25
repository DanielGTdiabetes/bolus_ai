package org.bolusai.companion.network

import kotlinx.coroutines.runBlocking
import org.bolusai.companion.dexcom.GlucoseReading
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GlucoseIngestClientTest {
    private val reading = GlucoseReading(123, 1_750_000_000, "Flat")

    @Test
    fun usesBackupWhenPrimaryFails() = runBlocking {
        val client = GlucoseIngestClient { _, _, _, endpoint ->
            if (endpoint == ActiveEndpoint.PRIMARY) {
                GlucoseIngestResult(false, endpoint, 503, "down")
            } else {
                GlucoseIngestResult(true, endpoint, 200, """{"status":"uploaded"}""")
            }
        }

        val result = client.send("https://primary", "https://backup", "key", reading)

        assertTrue(result.ok)
        assertEquals(ActiveEndpoint.BACKUP, result.endpoint)
    }

    @Test
    fun rejectsMissingIngestKeyWithoutNetworkCall() = runBlocking {
        var called = false
        val client = GlucoseIngestClient { _, _, _, endpoint ->
            called = true
            GlucoseIngestResult(true, endpoint, 200, "{}")
        }

        val result = client.send("https://primary", "https://backup", "", reading)

        assertEquals(false, result.ok)
        assertEquals(false, called)
    }
}
