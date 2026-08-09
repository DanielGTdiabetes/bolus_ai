package org.bolusai.companion.scale

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ScalePayloadParserTest {
    @Test
    fun parsesWeightFromPayload() {
        val reading = ScalePayloadParser.parse(
            byteArrayOf(0x00, 0x57, 0x00, 0x00, 0x01, 0xF4.toByte()),
        )

        assertEquals(500, reading?.grams)
    }

    @Test
    fun parsesPayloadCapturedFromRealProzisScale() {
        val reading = ScalePayloadParser.parse(
            byteArrayOf(0x06, 0x00, 0x00, 0x00, 0x00, 0xA2.toByte()),
        )

        assertEquals(162, reading?.grams)
    }

    @Test
    fun rejectsShortNegativeAndOutOfRangePayloads() {
        assertNull(ScalePayloadParser.parse(byteArrayOf(0x00, 0x50, 0x00)))
        assertNull(ScalePayloadParser.parse(byteArrayOf(0x00, 0x50, 0xFF.toByte(), 0xFF.toByte())))
        assertNull(ScalePayloadParser.parse(byteArrayOf(0x00, 0x50, 0x07, 0xD1.toByte())))
    }
}
