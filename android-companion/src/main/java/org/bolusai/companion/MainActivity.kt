package org.bolusai.companion

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.runtime.LaunchedEffect
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
import androidx.core.content.ContextCompat
import androidx.health.connect.client.PermissionController
import kotlinx.coroutines.launch
import org.bolusai.companion.data.AppSettings
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.diagnostics.HealthConnectLog
import org.bolusai.companion.diagnostics.HealthConnectLogRepository
import org.bolusai.companion.diagnostics.LogExporter
import org.bolusai.companion.diagnostics.LogShare
import org.bolusai.companion.diagnostics.HealthConnectLogStatus
import org.bolusai.companion.health.AutoExportPayloadBuilder
import org.bolusai.companion.health.HealthConnectAvailability
import org.bolusai.companion.health.HealthConnectState
import org.bolusai.companion.health.HealthPermissions
import org.bolusai.companion.health.NutritionRecordReader
import androidx.health.connect.client.HealthConnectClient
import org.bolusai.companion.network.NutritionIngestClient
import org.bolusai.companion.network.ServerStatus
import org.bolusai.companion.network.ServerStatusClient
import org.bolusai.companion.portal.PortalLauncher
import org.bolusai.companion.usage.UsageAccess
import org.bolusai.companion.worker.NutritionActiveSyncService
import org.bolusai.companion.worker.NutritionSyncScheduler

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NutritionSyncScheduler.schedule(this)
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

    LaunchedEffect(settings.nutritionSyncEnabled) {
        if (settings.nutritionSyncEnabled) {
            NutritionActiveSyncService.start(context)
        } else {
            NutritionActiveSyncService.stop(context)
        }
    }

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
    var healthStatus by remember { mutableStateOf("Comprobando Health Connect...") }
    var hasNutritionPermission by remember { mutableStateOf(false) }
    var requestedOnOpen by remember { mutableStateOf(false) }
    val launcher = remember { PortalLauncher(context) }
    val statusClient = remember { ServerStatusClient() }
    val reader = remember { NutritionRecordReader(context) }
    val payloadBuilder = remember { AutoExportPayloadBuilder() }
    val ingestClient = remember { NutritionIngestClient() }
    val availability = remember { HealthConnectAvailability(context).status() }
    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { }
    val permissionLauncher = rememberLauncherForActivityResult(
        PermissionController.createRequestPermissionResultContract(),
    ) { grantedPermissions ->
        hasNutritionPermission = grantedPermissions.containsAll(HealthPermissions.readPermissionsForRequest())
        healthStatus = if (hasNutritionPermission) {
            "Health Connect conectado: permisos de nutricion concedidos."
        } else {
            "Health Connect disponible, pero falta conceder permisos de nutricion."
        }
    }

    suspend fun refreshHealthPermission(): Boolean {
        if (availability != HealthConnectState.AVAILABLE) {
            healthStatus = when (availability) {
                HealthConnectState.NOT_INSTALLED -> "Health Connect requiere instalacion o actualizacion."
                HealthConnectState.NOT_SUPPORTED -> "Health Connect no esta soportado en este dispositivo."
                HealthConnectState.AVAILABLE -> healthStatus
            }
            hasNutritionPermission = false
            return false
        }

        val granted = HealthConnectClient
            .getOrCreate(context)
            .permissionController
            .getGrantedPermissions()
        hasNutritionPermission = granted.containsAll(HealthPermissions.readPermissionsForRequest())
        healthStatus = if (hasNutritionPermission) {
            "Health Connect conectado: permisos de nutricion concedidos."
        } else {
            "Health Connect disponible, pero falta conceder permisos de nutricion."
        }
        return hasNutritionPermission
    }

    LaunchedEffect(Unit) {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        val granted = refreshHealthPermission()
        if (availability == HealthConnectState.AVAILABLE && !granted && !requestedOnOpen) {
            requestedOnOpen = true
            permissionLauncher.launch(HealthPermissions.readPermissionsForRequest())
        }
    }

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
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Health Connect", style = MaterialTheme.typography.titleMedium)
                Text(healthStatus)
                Button(onClick = {
                    scope.launch {
                        val granted = refreshHealthPermission()
                        if (!granted && availability == HealthConnectState.AVAILABLE) {
                            permissionLauncher.launch(HealthPermissions.readPermissionsForRequest())
                        }
                    }
                }) { Text(if (hasNutritionPermission) "Revisar permisos" else "Conectar Health Connect") }
            }
        }
        Button(onClick = {
            scope.launch {
                if (!refreshHealthPermission()) {
                    if (availability == HealthConnectState.AVAILABLE) {
                        permissionLauncher.launch(HealthPermissions.readPermissionsForRequest())
                    }
                    return@launch
                }

                runCatching {
                    reader.readLatest(syncEnabled = true)
                }.onSuccess { records ->
                    val sentHashes = logRepository.sentDedupeHashes()
                    val uniqueRecords = records
                        .distinctBy { it.dedupeHash }
                        .filterNot { it.dedupeHash in sentHashes }
                    if (uniqueRecords.isEmpty()) {
                        healthStatus = "Sin comidas nuevas para enviar."
                        return@onSuccess
                    }

                    val payloadJson = payloadBuilder.build(uniqueRecords)
                    val result = ingestClient.send(
                        primaryUrl = settings.primaryUrl,
                        backupUrl = settings.backupUrl,
                        ingestKey = settings.ingestKey,
                        payloadJson = payloadJson,
                    )
                    val logStatus = when {
                        result.ok -> HealthConnectLogStatus.SENT
                        settings.ingestKey.isBlank() -> HealthConnectLogStatus.PENDING
                        else -> HealthConnectLogStatus.ERROR
                    }
                    uniqueRecords.forEach { record ->
                        logRepository.recordDetected(
                            record = record,
                            status = logStatus,
                            endpointUsed = result.endpoint.name.lowercase(),
                            backendResponseSanitized = "HTTP ${result.statusCode ?: "-"} ${result.body}",
                        )
                    }
                    healthStatus = if (result.ok) {
                        "Enviado AutoExport JSON: ${uniqueRecords.size} comidas (${result.endpoint.name.lowercase()})."
                    } else {
                        "Leidas ${uniqueRecords.size} comidas; envio pendiente/error: ${result.body}"
                    }
                }.onFailure { error ->
                    healthStatus = "Error leyendo Health Connect: ${error.message ?: error::class.java.simpleName}"
                }
            }
        }) { Text("Sincronizar comidas") }
        Text(if (settings.nutritionSyncEnabled) "Sincronización nutricional: ON" else "Sincronización nutricional: OFF")
    }
}

@Composable
private fun SettingsScreen(settings: AppSettings, repository: AppSettingsRepository) {
    val context = LocalContext.current
    var hasUsageAccess by remember { mutableStateOf(UsageAccess.hasPermission(context)) }
    var primary by remember(settings.primaryUrl) { mutableStateOf(settings.primaryUrl) }
    var backup by remember(settings.backupUrl) { mutableStateOf(settings.backupUrl) }
    var ingestKey by remember(settings.ingestKey) { mutableStateOf(settings.ingestKey) }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        OutlinedTextField(value = primary, onValueChange = { primary = it }, label = { Text("URL principal") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { repository.updatePrimaryUrl(primary) }) { Text("Guardar principal") }
        OutlinedTextField(value = backup, onValueChange = { backup = it }, label = { Text("URL backup") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { repository.updateBackupUrl(backup) }) { Text("Guardar backup") }
        OutlinedTextField(value = ingestKey, onValueChange = { ingestKey = it }, label = { Text("Clave de ingesta") }, modifier = Modifier.fillMaxWidth())
        Button(onClick = { repository.updateIngestKey(ingestKey) }) { Text("Guardar clave") }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Activar sincronización nutricional")
            Switch(
                checked = settings.nutritionSyncEnabled,
                onCheckedChange = { enabled ->
                    repository.setNutritionSyncEnabled(enabled)
                    if (enabled) {
                        NutritionActiveSyncService.start(context)
                    } else {
                        NutritionActiveSyncService.stop(context)
                    }
                },
            )
        }
        Text("Si esta ON, la vigilancia activa revisa Health Connect cada minuto.")
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Deteccion MyFitnessPal", style = MaterialTheme.typography.titleMedium)
                Text(if (hasUsageAccess) "Acceso de uso concedido." else "Falta Acceso de uso para detectar cuando sales de MyFitnessPal.")
                Button(onClick = {
                    context.startActivity(UsageAccess.settingsIntent())
                    hasUsageAccess = UsageAccess.hasPermission(context)
                }) { Text("Abrir Acceso de uso") }
            }
        }
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
