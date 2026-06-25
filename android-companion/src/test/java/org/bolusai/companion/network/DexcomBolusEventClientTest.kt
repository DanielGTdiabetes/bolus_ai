package org.bolusai.companion.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DexcomBolusEventClientTest {
    @Test
    fun parsesRapidLongActingAndCarbohydrateEvents() {
        val events = parseDexcomEvents(
            """
            [
              {
                "id": "treatment:a:rapid",
                "event_kind": "INSULIN",
                "insulin_type": "FAST_ACTING",
                "insulin_units": 3.25,
                "carbs_grams": null,
                "timestamp": 1000
              },
              {
                "id": "basal:b:long",
                "event_kind": "INSULIN",
                "insulin_type": "LONG_ACTING",
                "insulin_units": 16.0,
                "carbs_grams": null,
                "timestamp": 2000
              },
              {
                "id": "treatment:a:carbs",
                "event_kind": "CARBS",
                "insulin_type": null,
                "insulin_units": null,
                "carbs_grams": 43,
                "timestamp": 1000
              }
            ]
            """.trimIndent(),
        )

        assertEquals(3, events.size)
        assertEquals("FAST_ACTING", events[0].insulinType)
        assertEquals(3.25, events[0].insulinUnits!!, 0.0)
        assertEquals("LONG_ACTING", events[1].insulinType)
        assertEquals(16.0, events[1].insulinUnits!!, 0.0)
        assertEquals("CARBS", events[2].eventKind)
        assertEquals(43, events[2].carbsGrams)
        assertNull(events[2].insulinUnits)
    }
}
