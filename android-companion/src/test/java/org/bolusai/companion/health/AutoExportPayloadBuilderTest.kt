package org.bolusai.companion.health

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

class AutoExportPayloadBuilderTest {
    @Test
    fun mapsNutritionRecordToAutoExportMetricsPayload() {
        val payload = AutoExportPayloadBuilder(ZoneId.of("UTC")).build(listOf(sampleRecord()))
        val root = JSONObject(payload)
        val metrics = root.getJSONObject("data").getJSONArray("metrics")

        assertEquals(4, metrics.length())
        assertTrue(payload.contains("\"name\":\"carbohydrates\""))
        assertTrue(payload.contains("\"qty\":42"))
        assertTrue(payload.contains("\"source\":\"MyFitnessPal\""))
        assertTrue(payload.contains("\"meal_fingerprint\""))
    }
}
