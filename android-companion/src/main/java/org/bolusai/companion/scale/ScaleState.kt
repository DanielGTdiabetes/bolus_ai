package org.bolusai.companion.scale

data class ScaleState(
    val scanning: Boolean = false,
    val connecting: Boolean = false,
    val connected: Boolean = false,
    val deviceName: String? = null,
    val grams: Int = 0,
    val batteryPercent: Int? = null,
    val stable: Boolean = false,
    val message: String = "Báscula desconectada",
)
