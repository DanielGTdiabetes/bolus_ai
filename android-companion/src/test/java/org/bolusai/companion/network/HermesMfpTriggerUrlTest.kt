package org.bolusai.companion.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HermesMfpTriggerUrlTest {
    @Test
    fun keepsCurrentAndNewHostsWithoutMigratingThemAutomatically() {
        for (url in listOf("http://100.65.212.74:8776", "http://100.93.23.103:8776", "https://custom.example/hermes")) {
            assertEquals(url, normalizeHermesMfpTriggerBaseUrl(url))
        }
    }

    @Test
    fun trimsOnlyOuterWhitespaceAndTrailingSlashes() {
        assertEquals("http://host.example:8776", normalizeHermesMfpTriggerBaseUrl("  http://host.example:8776///  "))
        assertEquals("https://host.example/prefix", normalizeHermesMfpTriggerBaseUrl("https://host.example/prefix/"))
    }

    @Test
    fun rejectsFullEndpointToPreventDoubleRoute() {
        for (suffix in listOf("/mfp/sync-now", "/mfp/sync-now/", "/prefix/mfp/sync-now", "/%6dfp/sync-now")) {
            assertNull(normalizeHermesMfpTriggerBaseUrl("http://host.example:8776$suffix"))
        }
    }

    @Test
    fun rejectsCredentialsParametersAndInvalidAddresses() {
        for (url in listOf("", "server:8776", "file:///tmp/test", "ws://host.example", "http:///missing-host",
            "http://user:secret@host.example", "http://host.example?key=test", "https://host.example#fragment",
            "http://host.example:0", "http://host.example:65536", "http://host.example:", "http://host name")) {
            assertNull("Should reject $url", normalizeHermesMfpTriggerBaseUrl(url))
        }
    }

    @Test
    fun acceptsIpv6WithoutChangingItsAuthority() {
        assertEquals("http://[::1]:8776", normalizeHermesMfpTriggerBaseUrl("http://[::1]:8776/"))
    }
}
