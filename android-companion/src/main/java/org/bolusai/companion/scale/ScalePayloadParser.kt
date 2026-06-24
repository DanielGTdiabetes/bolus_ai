package org.bolusai.companion.scale

data class ScaleReading(
    val grams: Int,
    val batteryPercent: Int,
)

object ScalePayloadParser {
    fun parse(value: ByteArray): ScaleReading? {
        if (value.size < 4) return null
        val raw = ((value[value.size - 2].toInt() and 0xFF) shl 8) or
            (value[value.size - 1].toInt() and 0xFF)
        val grams = if (raw and 0x8000 != 0) raw - 0x10000 else raw
        if (grams !in 0..2_000) return null
        return ScaleReading(
            grams = grams,
            batteryPercent = (value[1].toInt() and 0xFF).coerceIn(0, 100),
        )
    }
}
