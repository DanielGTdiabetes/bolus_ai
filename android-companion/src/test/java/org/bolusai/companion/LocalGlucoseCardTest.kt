package org.bolusai.companion

import org.bolusai.companion.dexcom.GlucoseReading
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalGlucoseCardTest {
    private val now = 1_800_000_000_000L

    @Test
    fun recentDexcomReadingIsShownAsCurrent() {
        val display = localGlucoseDisplay(readingAt(now - 5 * 60_000), now)
        assertTrue(display.current)
        assertTrue(display.value.contains("123 mg/dL"))
        assertTrue(display.detail.contains("Dexcom en este móvil"))
    }

    @Test
    fun oldAndHistoricalReadingsRemainVisibleButNotCurrent() {
        val old = localGlucoseDisplay(readingAt(now - 13 * 60_000), now)
        val historical = localGlucoseDisplay(readingAt(now - 60_000).copy(historical = true), now)
        assertFalse(old.current)
        assertTrue(old.detail.contains("Lectura antigua"))
        assertFalse(historical.current)
        assertTrue(historical.detail.contains("Lectura no actual"))
    }

    @Test
    fun missingAndFutureReadingsAreNotCurrent() {
        assertFalse(localGlucoseDisplay(null, now).current)
        val future = localGlucoseDisplay(readingAt(now + 60_000), now)
        assertFalse(future.current)
        assertTrue(future.detail.contains("Hora de lectura futura"))
    }

    private fun readingAt(timestampMillis: Long) = GlucoseReading(
        glucoseMgdl = 123,
        timestampSeconds = timestampMillis / 1_000,
        trendArrow = "Flat",
    )
}
