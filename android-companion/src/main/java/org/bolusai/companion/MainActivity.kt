package org.bolusai.companion

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
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
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import kotlinx.coroutines.launch
import org.bolusai.companion.data.AppSettings
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.diagnostics.HealthConnectLog
import org.bolusai.companion.diagnostics.HealthConnectLogRepository
import org.bolusai.companion.diagnostics.LogExporter
import org.bolusai.companion.diagnostics.LogShare
import org.bolusai.companion.health.HealthConnectAvailability
import org.bolusai.companion.health.HealthConnectState
import org.bolusai.companion.health.HealthPermissions
import org.bolusai.companion.network.ActiveEndpoint
import org.bolusai.companion.network.ServerStatus
import org.bolusai.companion.network.ServerStatusClient
import org.bolusai.companion.portal.PortalLauncher
import org.bolusai.companion.queue.MealQueueItem
import org.bolusai.companion.queue.MealQueueRepository
import org.bolusai.companion.usage.UsageAccess
import org.bolusai.companion.worker.NutritionActiveSyncService
import org.bolusai.companion.worker.NutritionSyncRunner
import org.bolusai.companion.worker.NutritionSyncScheduler
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NutritionSyncScheduler.schedule(this)
        setContent { BolusCompanionApp() }
    }
}

private enum class CompanionScreen(val label: String) {
    HOME("Inicio"),
    MEALS("Comidas"),
    DIAGNOSTICS("Diagnostico"),
    SETTINGS("Ajustes"),
    WEB("Web"),
}

@Composable
fun BolusCompanionApp() {
    val context = LocalContext.current
    val settingsRepository = remember { AppSettingsRepository(context) }
    val logRepository = remember { HealthConnectLogRepository(context) }
    val queueRepository = remember { MealQueueRepository(context) }
    val settings by settingsRepository.observe().collectAsState()
    val logs by logRepository.observe().collectAsState()
    val queueItems by queueRepository.observeRecent().collectAsState(initial = emptyList())
    var screen by remember { mutableStateOf(CompanionScreen.HOME) }

    LaunchedEffect(settings.nutritionSyncEnabled) {
        if (settings.nutritionSyncEnabled) NutritionActiveSyncService.start(context) else NutritionActiveSyncService.stop(context)
    }

    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(modifier = Modifier.fillMaxSize()) {
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    Text("Bolus AI", style = MaterialTheme.typography.headlineMedium)
                    when (screen) {
                        CompanionScreen.HOME -> HomeScreen(settings, queueItems) { screen = it }
                        CompanionScreen.MEALS -> MealsScreen(queueItems)
                        CompanionScreen.DIAGNOSTICS -> DiagnosticsScreen(settings, logs, queueItems, logRepository, queueRepository)
                        CompanionScreen.SETTINGS -> SettingsScreen(settings, settingsRepository)
                        CompanionScreen.WEB -> WebScreen(settings)
                    }
                }
                NavigationBar {
                    CompanionScreen.entries.forEach { item ->
                        NavigationBarItem(
                            selected = screen == item,
                            onClick = { screen = item },
                            label = { Text(item.label) },
                            icon = {},
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun HomeScreen(settings: AppSettings, queueItems: List<MealQueueItem>, navigate: (CompanionScreen) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var serverStatus by remember { mutableStateOf(ServerStatus()) }
    var syncMessage by remember { mutableStateOf("Sin sincronizacion manual reciente") }
    val statusClient = remember { ServerStatusClient() }
    val pendingCount = queueItems.count { it.status.name in setOf("QUEUED", "SENDING", "FAILED", "NEEDS_RETRY") }
    val lastMeal = queueItems.maxByOrNull { it.updatedAt }

    LaunchedEffect(settings.primaryUrl, settings.backupUrl) {
        serverStatus = statusClient.resolve(settings.primaryUrl, settings.backupUrl)
    }

    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            StatusCard(
                title = "Servidor",
                body = when (serverStatus.activeEndpoint) {
                    ActiveEndpoint.PRIMARY -> "Principal"
                    ActiveEndpoint.BACKUP -> "Backup"
                    ActiveEndpoint.NONE -> "Sin conexion"
                },
                detail = serverStatus.message,
            )
        }
        item {
            StatusCard(
                title = "Sincronizacion",
                body = if (settings.nutritionSyncEnabled) "Activa" else "Desactivada",
                detail = "$syncMessage. Cola pendiente: $pendingCount",
            )
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Ultima comida", style = MaterialTheme.typography.titleMedium)
                    if (lastMeal == null) {
                        Text("Aun no hay comidas detectadas")
                    } else {
                        Text(formatInstant(lastMeal.startTime))
                        Text(macros(lastMeal))
                        Text("Estado: ${lastMeal.status}")
                        Text("Ultimo sync: ${formatInstantMillis(lastMeal.updatedAt)}")
                    }
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    syncMessage = "Sincronizando"
                    scope.launch {
                        val result = NutritionSyncRunner(context).run()
                        syncMessage = result.message
                    }
                }) { Text("Sincronizar ahora") }
                OutlinedButton(onClick = { navigate(CompanionScreen.DIAGNOSTICS) }) { Text("Diagnostico") }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { navigate(CompanionScreen.SETTINGS) }) { Text("Ajustes") }
                OutlinedButton(onClick = { navigate(CompanionScreen.WEB) }) { Text("Abrir Bolus AI") }
            }
        }
    }
}

@Composable
private fun StatusCard(title: String, body: String, detail: String) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(body, style = MaterialTheme.typography.headlineSmall)
            Text(detail)
        }
    }
}

@Composable
private fun MealsScreen(queueItems: List<MealQueueItem>) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(queueItems, key = { it.id }) { item ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("${formatInstant(item.startTime)} - ${item.status}", style = MaterialTheme.typography.titleSmall)
                    Text(macros(item))
                    Text("Endpoint: ${item.endpointUsed ?: "-"} - intentos: ${item.attemptCount}")
                    Text("metadata.id: ${item.metadataId.ifBlank { "-" }}")
                    Text("dedupe_hash: ${item.dedupeHash.take(16)}...")
                    if (!item.lastError.isNullOrBlank()) Text("Error: ${item.lastError}")
                }
            }
        }
    }
}

@Composable
private fun SettingsScreen(settings: AppSettings, repository: AppSettingsRepository) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var hasUsageAccess by remember { mutableStateOf(UsageAccess.hasPermission(context)) }
    var primary by remember(settings.primaryUrl) { mutableStateOf(settings.primaryUrl) }
    var backup by remember(settings.backupUrl) { mutableStateOf(settings.backupUrl) }
    var ingestKey by remember(settings.ingestKey) { mutableStateOf(settings.ingestKey) }
    var connectionMessage by remember { mutableStateOf("") }
    var healthStatus by remember { mutableStateOf("Sin comprobar") }
    val availability = remember { HealthConnectAvailability(context).status() }
    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { }
    val permissionLauncher = rememberLauncherForActivityResult(
        PermissionController.createRequestPermissionResultContract(),
    ) { granted ->
        healthStatus = if (granted.containsAll(HealthPermissions.readPermissionsForRequest())) "Permisos concedidos" else "Faltan permisos"
    }

    suspend fun refreshHealthPermissions(): Boolean {
        if (availability != HealthConnectState.AVAILABLE) {
            healthStatus = availability.toString()
            return false
        }
        val granted = HealthConnectClient.getOrCreate(context).permissionController.getGrantedPermissions()
        val ok = granted.containsAll(HealthPermissions.readPermissionsForRequest())
        healthStatus = if (ok) "Permisos concedidos" else "Faltan permisos"
        return ok
    }

    LaunchedEffect(Unit) {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        refreshHealthPermissions()
    }

    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { SettingsTextField("Servidor principal", primary) { primary = it } }
        item { Button(onClick = { repository.updatePrimaryUrl(primary) }) { Text("Guardar principal") } }
        item { SettingsTextField("Servidor backup", backup) { backup = it } }
        item { Button(onClick = { repository.updateBackupUrl(backup) }) { Text("Guardar backup") } }
        item { SettingsTextField("Ingest key", ingestKey) { ingestKey = it } }
        item { Button(onClick = { repository.updateIngestKey(ingestKey) }) { Text("Guardar clave") } }
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Sync ON/OFF")
                Switch(
                    checked = settings.nutritionSyncEnabled,
                    onCheckedChange = { enabled -> repository.setNutritionSyncEnabled(enabled) },
                )
            }
        }
        item { Text("Modo sync: Health Connect + cola persistente") }
        item {
            Button(onClick = {
                scope.launch {
                    connectionMessage = ServerStatusClient().resolve(settings.primaryUrl, settings.backupUrl).message
                }
            }) { Text("Probar conexion") }
        }
        if (connectionMessage.isNotBlank()) item { Text(connectionMessage) }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Permisos Health Connect", style = MaterialTheme.typography.titleMedium)
                    Text(healthStatus)
                    Button(onClick = {
                        scope.launch {
                            if (!refreshHealthPermissions() && availability == HealthConnectState.AVAILABLE) {
                                permissionLauncher.launch(HealthPermissions.readPermissionsForRequest())
                            }
                        }
                    }) { Text("Revisar permisos") }
                }
            }
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Deteccion MyFitnessPal", style = MaterialTheme.typography.titleMedium)
                    Text(if (hasUsageAccess) "Acceso de uso concedido" else "Falta Acceso de uso")
                    Button(onClick = {
                        context.startActivity(UsageAccess.settingsIntent())
                        hasUsageAccess = UsageAccess.hasPermission(context)
                    }) { Text("Abrir Acceso de uso") }
                }
            }
        }
    }
}

@Composable
private fun SettingsTextField(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(value = value, onValueChange = onChange, label = { Text(label) }, modifier = Modifier.fillMaxWidth())
}

@Composable
private fun DiagnosticsScreen(
    settings: AppSettings,
    logs: List<HealthConnectLog>,
    queueItems: List<MealQueueItem>,
    logRepository: HealthConnectLogRepository,
    queueRepository: MealQueueRepository,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val exporter = remember { LogExporter() }
    val share = remember { LogShare(context) }
    var exportPreview by remember { mutableStateOf("") }
    val last = queueItems.firstOrNull()

    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text("Health Connect: ${HealthConnectAvailability(context).status()}") }
        item { Text("Sync nutricional: ${if (settings.nutritionSyncEnabled) "ON" else "OFF"}") }
        item { Text("Cola: ${queueItems.size} elementos - ultimo endpoint: ${last?.endpointUsed ?: "-"}") }
        item { Text("Ultimo error: ${last?.lastError ?: "-"}") }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    exportPreview = exporter.queueToJson(queueItems, logs)
                    share.shareText(exportPreview, "application/json")
                }) { Text("Exportar JSON") }
                Button(onClick = {
                    exportPreview = exporter.queueToText(queueItems, logs)
                    share.shareText(exportPreview, "text/plain")
                }) { Text("Exportar TXT") }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = {
                    scope.launch {
                        queueRepository.requeueFailed()
                        NutritionSyncScheduler.syncNow(context)
                    }
                }) { Text("Reintentar cola") }
                OutlinedButton(onClick = {
                    scope.launch {
                        queueRepository.clear()
                        logRepository.clear()
                    }
                }) { Text("Borrar logs") }
            }
        }
        if (exportPreview.isNotBlank()) item { Card(Modifier.fillMaxWidth()) { Text(exportPreview.take(2_000), Modifier.padding(12.dp)) } }
        items(queueItems, key = { it.id }) { item ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("${item.status} - ${item.sourcePackage}", style = MaterialTheme.typography.titleSmall)
                    Text("metadata.id: ${item.metadataId.ifBlank { "-" }}")
                    Text("dedupe_hash: ${item.dedupeHash}")
                    Text("payload: ${item.payloadJson.take(300)}")
                    Text("respuesta: ${item.backendResponse ?: "-"}")
                    Text("next_retry_at: ${formatInstantMillis(item.nextRetryAt)}")
                }
            }
        }
    }
}

@Composable
private fun WebScreen(settings: AppSettings) {
    val context = LocalContext.current
    val launcher = remember { PortalLauncher(context) }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Portal web", style = MaterialTheme.typography.titleMedium)
        Text("Se abre con navegador/TWA compatible o Custom Tabs cuando el sistema lo soporte.")
        Button(onClick = { launcher.open(settings.primaryUrl) }) { Text("Abrir Bolus AI") }
    }
}

private fun macros(item: MealQueueItem): String =
    "HC ${item.carbohydratesGrams ?: 0.0}g - P ${item.proteinGrams ?: 0.0}g - G ${item.fatGrams ?: 0.0}g - Fibra ${item.fiberGrams ?: 0.0}g - kcal ${item.caloriesKcal ?: 0.0}"

private fun formatInstant(value: String): String =
    runCatching { formatInstantMillis(Instant.parse(value).toEpochMilli()) }.getOrDefault(value)

private fun formatInstantMillis(value: Long): String =
    DateTimeFormatter.ofPattern("dd/MM HH:mm")
        .format(Instant.ofEpochMilli(value).atZone(ZoneId.systemDefault()))
