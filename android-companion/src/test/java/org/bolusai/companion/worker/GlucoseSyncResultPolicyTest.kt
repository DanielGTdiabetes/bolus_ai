package org.bolusai.companion.worker

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GlucoseSyncResultPolicyTest {
    @Test
    fun retriesTransientFailures() {
        assertTrue(GlucoseSyncResultPolicy.shouldRetry(null))
        assertTrue(GlucoseSyncResultPolicy.shouldRetry(408))
        assertTrue(GlucoseSyncResultPolicy.shouldRetry(429))
        assertTrue(GlucoseSyncResultPolicy.shouldRetry(500))
        assertTrue(GlucoseSyncResultPolicy.shouldRetry(503))
    }

    @Test
    fun doesNotAggressivelyRetryConfigurationOrPayloadFailures() {
        assertFalse(GlucoseSyncResultPolicy.shouldRetry(400))
        assertFalse(GlucoseSyncResultPolicy.shouldRetry(401))
        assertFalse(GlucoseSyncResultPolicy.shouldRetry(403))
        assertFalse(GlucoseSyncResultPolicy.shouldRetry(422))
    }
}
