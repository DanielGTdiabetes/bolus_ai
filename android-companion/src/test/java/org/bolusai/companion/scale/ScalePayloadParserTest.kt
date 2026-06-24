package org.bolusai.companion.scale

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ScalePayloadParserTest {
    @Test
    fun parsesWeightAndBatteryFromPayload() {
        val reading = ScalePayloadParser.parse(
            byteArrayOf(0x00, 0x57, 0x00, 0x00, 0x01, 0xF4.toByte()),
        )

        assertEquals(500, reading?.grams)
        assertEquals(87, reading?.batteryPercent)
    }

    @Test
    fun clampsBatteryPercentage() {
        val reading = ScalePayloadParser.parse(
            byteArrayOf(0x00, 0xFF.toByte(), 0x00, 0x64),
        )

        assertEquals(100, reading?.batteryPercent)
    }

    @Test
    fun rejectsShortNegativeAndOutOfRangePayloads() {
        assertNull(ScalePayloadParser.parse(byteArrayOf(0x00, 0x50, 0x00)))
        assertNull(ScalePayloadParser.parse(byteArrayOf(0x00, 0x50, 0xFF.toByte(), 0xFF.toByte())))
        assertNull(ScalePayloadParser.parse(byteArrayOf(0x00, 0x50, 0x07, 0xD1.toByte())))
    }
}
