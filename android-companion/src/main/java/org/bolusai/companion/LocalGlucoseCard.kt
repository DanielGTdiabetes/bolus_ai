package org.bolusai.companion

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import org.bolusai.companion.dexcom.GlucoseQueueRepository
import org.bolusai.companion.dexcom.GlucoseReading
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

internal data class LocalGlucoseDisplay(
    val value: String,
    val detail: String,
    val current: Boolean,
)

internal fun localGlucoseDisplay(reading: GlucoseReading?, nowMillis: Long): LocalGlucoseDisplay {
    if (reading == null) return LocalGlucoseDisplay("--", "Esperando una lectura de Dexcom", false)
    val ageMillis = nowMillis - reading.timestampSeconds * 1_000
    val time = DateTimeFormatter.ofPattern("HH:mm")
        .format(Instant.ofEpochSecond(reading.timestampSeconds).atZone(ZoneId.systemDefault()))
    val ageMinutes = (ageMillis.coerceAtLeast(0) / 60_000)
    val ageLabel = "a las $time · hace $ageMinutes min"
    val detail = when {
        ageMillis < 0 -> "Hora de lectura futura · comprobar reloj del móvil"
        reading.historical || reading.timestampUncertain || reading.displayOnly ->
            "Lectura no actual · $ageLabel"
        ageMillis > 12 * 60_000 -> "Lectura antigua · $ageLabel"
        else -> "Dexcom en este móvil · $ageLabel"
    }
    return LocalGlucoseDisplay(
        value = "${reading.glucoseMgdl} mg/dL ${reading.trendArrow.takeIf { it != "NONE" }.orEmpty()}",
        detail = detail,
        current = ageMillis in 0..(12 * 60_000) &&
            !reading.historical && !reading.timestampUncertain && !reading.displayOnly,
    )
}

@Composable
internal fun LocalGlucoseCard(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val repository = remember { GlucoseQueueRepository(context) }
    var reading by remember { mutableStateOf(repository.latestForDisplay()) }
    var nowMillis by remember { mutableStateOf(System.currentTimeMillis()) }

    LaunchedEffect(Unit) {
        while (true) {
            nowMillis = System.currentTimeMillis()
            reading = repository.latestForDisplay()
            delay(5_000)
        }
    }
    val display = localGlucoseDisplay(reading, nowMillis)
    Card(modifier.fillMaxWidth()) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Glucosa local", style = MaterialTheme.typography.labelLarge)
                Text(if (display.current) "Actual" else "No actual", style = MaterialTheme.typography.labelMedium)
            }
            Text(display.value, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(display.detail, style = MaterialTheme.typography.bodySmall)
        }
    }
}
