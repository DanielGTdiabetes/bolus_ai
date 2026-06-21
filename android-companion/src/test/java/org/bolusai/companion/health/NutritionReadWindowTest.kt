package org.bolusai.companion.health

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Instant
import java.time.ZoneId

class NutritionReadWindowTest {
    @Test
    fun latestWindowOnlyReadsCurrentLocalDay() {
        val now = Instant.parse("2026-06-20T06:29:00Z")
        val window = NutritionReadWindow.latest(now, ZoneId.of("Europe/Madrid"))

        assertEquals(Instant.parse("2026-06-19T22:00:00Z"), window.start)
        assertEquals(Instant.parse("2026-06-20T22:00:00Z"), window.end)
    }
}
