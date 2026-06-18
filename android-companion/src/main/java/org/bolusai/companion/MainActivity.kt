package org.bolusai.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import org.bolusai.companion.data.AppSettings
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.diagnostics.HealthConnectLog
import org.bolusai.companion.diagnostics.HealthConnectLogRepository
import org.bolusai.companion.diagnostics.LogExporter
import org.bolusai.companion.diagnostics.LogShare
import org.bolusai.companion.health.HealthConnectAvailability
import org.bolusai.companion.health.HealthPermissions
import org.bolusai.companion.health.NutritionRecordReader
import androidx.health.connect.client.HealthConnectClient
import org.bolusai.companion.network.ServerStatus
import org.bolusai.companion.network.ServerStatusClient
import org.bolusai.companion.portal.PortalLauncher

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { BolusCompanionApp() }
    }
}

private enum class CompanionScreen { HOME, SETTINGS, DIAGNOSTICS }

@Composable
fun BolusCompanionApp() {
    val context = LocalContext.current
    val settingsRepository = remember { AppSettingsRepository(context) }
    val logRepository = remember { HealthConnectLogRepository(context) }
    val settings by settingsRepository.observe().collectAsState()
    val logs by logRepository.observe().collectAsState()
    var screen by remember { mutableStateOf(CompanionScreen.HOME) }

    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(modifier = Modifier.fillMaxSize().padding(20.dp)) {
                Text("Bolus AI Companion", style = MaterialTheme.typography.headlineMedium)
                Text("Fase 1 + Fase 2: portal, ajustes, diagnóstico y lectura manual Health Connect")
                Spacer(Modifier.height(16.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { screen = CompanionScreen.HOME }) { Text("Home") }
                    Button(onClick = { screen = CompanionScreen.SETTINGS }) { Text("Ajustes") }
                    Button(onClick = { screen = CompanionScreen.DIAGNOSTICS }) { Text("Diagnóstico") }
                }
                Spacer(Modifier.height(16.dp))
                when (screen) {
                    CompanionScreen.HOME -> HomeScreen(settings, logRepository)
                    CompanionScreen.SETTINGS -> SettingsScreen(settings, settingsRepository)
                    CompanionScreen.DIAGNOSTICS -> DiagnosticsScreen(settings, logs, logRepository)
                }
            }
        }
    }
}

@Composable
private fun HomeScreen(settings: AppSettings, logRepository: HealthConnectLogRepository) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var status by remember { mutableStateOf(ServerStatus()) }
    val launcher = remember { PortalLauncher(context) }
    val statusClient = remember { ServerStatusClient() }
    val reader = remember { NutritionRecordReader(context) }
    val permissionLauncher = rememberLauncherForActivityResult(
        HealthConnectClient.getOrCreate(context).permissionController.createRequestPermissionResultContract(),
    ) { }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Servidor", style = MaterialTheme.typography.titleMedium)
                Text(status.message)
                Button(onClick = {
                    scope.launch { status = statusClient.resolve(settings.primaryUrl, settings.backupUrl) }
                }) { Text("Probar conexión") }
            }
        }
        Button(onClick = { launcher.open(settings.primaryUrl) }) { Text("Abrir Bolus AI") }
        Button(onClick = { permissionLauncher.launch(HealthPermissions.nutritionReadPermissions) }) { Text("Permisos Health Connect") }
        Button(onClick = {
            scope.launch {
                reader.readLatest(settings.nutritionSyncEnabled).forEach(logRepository::recordDetected)
            }
        }) { Text("Buscar comidas nuevas") }
        Text(if (settings.nutritionSyncEnabled) "Sincronización nutricional: ON" else "Sincronización nutricional: OFF")
    }
}

@Composable
private fun SettingsScreen(settings: AppSettings, repository: AppSettingsRepository) {
    var primary by remember(settings.primaryUrl) { mutableStateOf(settings.primaryUrl) }
    var backup by remember(settings.backupUrl) { mutableStateOf(settings.backupUrl) }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        OutlinedTextField(value = primary, onValueChange = { primary = it }, label = { Text("URL principal") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { repository.updatePrimaryUrl(primary) }) { Text("Guardar principal") }
        OutlinedTextField(value = backup, onValueChange = { backup = it }, label = { Text("URL backup") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { repository.updateBackupUrl(backup) }) { Text("Guardar backup") }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Activar sincronización nutricional")
            Switch(checked = settings.nutritionSyncEnabled, onCheckedChange = repository::setNutritionSyncEnabled)
        }
        Text("Si está OFF, no se lee Health Connect ni se crean logs nuevos.")
        Text("Retención de logs")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(7, 30, 90).forEach { days ->
                Button(onClick = { repository.setLogRetentionDays(days) }) {
                    Text(if (settings.logRetentionDays == days) "$days días ✓" else "$days días")
                }
            }
        }
    }
}

@Composable
private fun DiagnosticsScreen(settings: AppSettings, logs: List<HealthConnectLog>, repository: HealthConnectLogRepository) {
    val context = LocalContext.current
    val availability = remember { HealthConnectAvailability(context).status() }
    val exporter = remember { LogExporter() }
    val share = remember { LogShare(context) }
    var exportPreview by remember { mutableStateOf("") }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Health Connect: $availability")
        Text("Sync nutricional: ${if (settings.nutritionSyncEnabled) "ON" else "OFF"}")
        Text("Retención configurada: ${settings.logRetentionDays} días")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                exportPreview = exporter.toJson(logs)
                share.shareText(exportPreview, "application/json")
            }) { Text("Exportar JSON") }
            Button(onClick = {
                exportPreview = exporter.toText(logs)
                share.shareText(exportPreview, "text/plain")
            }) { Text("Exportar TXT") }
            Button(onClick = repository::clear) { Text("Borrar logs") }
        }
        if (exportPreview.isNotBlank()) {
            Card(Modifier.fillMaxWidth()) { Text(exportPreview.take(2_000), Modifier.padding(12.dp)) }
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(logs) { log ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("${log.status} · ${log.record.sourcePackage}")
                        Text("metadata.id: ${log.record.metadataId}")
                        Text("start/end: ${log.record.startTime} → ${log.record.endTime}")
                        Text("macros: C ${log.record.carbohydratesGrams} · P ${log.record.proteinGrams} · G ${log.record.fatGrams} · Fibra ${log.record.fiberGrams} · kcal ${log.record.caloriesKcal}")
                        Text("mealType: ${log.record.mealType}")
                        Text("dedupe_hash: ${log.record.dedupeHash}")
                    }
                }
            }
        }
    }
}
