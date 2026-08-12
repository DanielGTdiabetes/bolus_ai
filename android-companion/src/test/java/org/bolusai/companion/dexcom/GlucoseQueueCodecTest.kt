package org.bolusai.companion.dexcom

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GlucoseQueueCodecTest {
    @Test
    fun mergeDeduplicatesSortsAndKeepsNewestEntries() {
        val old = GlucoseReading(100, 1_750_000_000, "Flat")
        val duplicate = old.copy()
        val middle = GlucoseReading(110, 1_750_000_300, "SingleUp")
        val newest = GlucoseReading(120, 1_750_000_600, "Flat")

        val merged = GlucoseQueueCodec.merge(
            existing = listOf(middle, old),
            incoming = listOf(newest, duplicate),
            maxSize = 2,
        )

        assertEquals(listOf(middle, newest), merged)
    }

    @Test
    fun encodedQueueRoundTripsAndDropsMalformedInput() {
        val readings = listOf(
            GlucoseReading(95, 1_750_000_000, "Flat"),
            GlucoseReading(105, 1_750_000_300, "FortyFiveUp"),
        )

        assertEquals(readings, GlucoseQueueCodec.decode(GlucoseQueueCodec.encode(readings)))
        assertTrue(GlucoseQueueCodec.decode("not-json").isEmpty())
    }

    @Test
    fun readingUidIsTheIdempotentQueueIdentity() {
        val original = GlucoseReading(95, 1_750_000_000, "Flat", readingUid = "g7-uid-42")
        val replay = GlucoseReading(96, 1_750_000_001, "SingleUp", readingUid = "g7-uid-42")

        val merged = GlucoseQueueCodec.merge(listOf(original), listOf(replay), maxSize = 10)

        assertEquals(listOf(original), merged)
    }
}
