package org.bolusai.companion.dexcom

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DexcomEventSyncLedgerTest {
    @Test
    fun boundedLedgerKeepsNewestKeysInStableOrder() {
        val updated = rememberBoundedKeys(
            existing = listOf("old-1", "old-2", "current"),
            additions = listOf("old-2", "new"),
            maxSize = 3,
        )

        assertEquals(listOf("current", "old-2", "new"), updated)
    }

    @Test
    fun encodedLedgerRoundTripsWithoutLosingOrder() {
        val keys = listOf("treatment:one:rapid", "basal:two:long")
        assertEquals(keys, decodeOrderedKeys(encodeOrderedKeys(keys)))
    }

    @Test
    fun insulinFingerprintUsesDoseTypeAndOriginalTimestamp() {
        val basal = insulinEventFingerprint("LONG_ACTING", 17.0, 1234L)

        assertEquals(basal, insulinEventFingerprint("long_acting", 17.0, 1234L))
        assertFalse(basal == insulinEventFingerprint("LONG_ACTING", 16.0, 1234L))
        assertFalse(basal == insulinEventFingerprint("LONG_ACTING", 17.0, 1235L))
        assertTrue(basal.contains("LONG_ACTING"))
    }
}
