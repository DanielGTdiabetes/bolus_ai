package org.bolusai.companion.network

import kotlinx.coroutines.runBlocking
import org.bolusai.companion.bolus.BolusProfile
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MobileBolusSettingsClientTest {
    @Test
    fun usesBackupWhenPrimaryFails() = runBlocking {
        val client = MobileBolusSettingsClient { _, _, endpoint ->
            when (endpoint) {
                ActiveEndpoint.PRIMARY -> MobileBolusSettingsResult(false, endpoint, null, "timeout")
                ActiveEndpoint.BACKUP -> MobileBolusSettingsResult(true, endpoint, BolusProfile(userId = "admin"), "ok")
                ActiveEndpoint.NONE -> error("not used")
            }
        }

        val result = client.sync("https://primary", "https://backup", "key")

        assertTrue(result.ok)
        assertEquals(ActiveEndpoint.BACKUP, result.endpoint)
        assertEquals("admin", result.profile?.userId)
    }

    @Test
    fun failsFastWithoutIngestKey() = runBlocking {
        val client = MobileBolusSettingsClient { _, _, _ -> error("not used") }

        val result = client.sync("https://primary", "https://backup", "")

        assertEquals(false, result.ok)
        assertEquals(ActiveEndpoint.NONE, result.endpoint)
    }
}
