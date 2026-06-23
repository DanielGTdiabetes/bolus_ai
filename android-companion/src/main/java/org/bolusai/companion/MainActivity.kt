package org.bolusai.companion

import android.Manifest
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.accessibility.AccessibilityManager
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
import org.bolusai.companion.accessibility.MyFitnessPalAssistantService
import org.bolusai.companion.diagnostics.HealthConnectLog
import org.bolusai.companion.diagnostics.HealthConnectLogRepository
import org.bolusai.companion.diagnostics.LogExporter
import org.bolusai.companion.diagnostics.LogShare
import org.bolusai.companion.health.HealthConnectAvailability
import org.bolusai.companion.health.HealthConnectState
import org.bolusai.companion.health.HealthPermissions
import org.bolusai.companion.network.ActiveEndpoint
import org.bolusai.companion.network.NutritionIngestClient
import org.bolusai.companion.network.ServerStatus
import org.bolusai.companion.network.ServerStatusClient
import org.bolusai.companion.portal.PortalLauncher
import org.bolusai.companion.queue.MealQueueItem
import org.bolusai.companion.queue.MealQueueRepository
import org.bolusai.companion.health.NutritionRecordSnapshot
import org.bolusai.companion.usage.UsageAccess
import org.bolusai.companion.worker.NutritionActiveSyncService
import org.bolusai.companion.worker.NutritionSyncRunner
import org.bolusai.companion.worker.NutritionSyncScheduler
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import org.bolusai.companion.bolus.BolusCalculationInput
import org.bolusai.companion.bolus.BolusCalculationResult
import org.bolusai.companion.bolus.BolusCalculator
import org.bolusai.companion.bolus.BolusProfile
import org.bolusai.companion.bolus.BolusProfileRepository
import org.bolusai.companion.network.MobileBolusSettingsClient

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NutritionSyncScheduler.schedule(this)
        setContent { BolusCompanionApp() }
    }
}

private enum class CompanionScreen(val label: String) {
    HOME("Inicio"),
    BOLUS("Bolo"),
    MEALS("Comidas"),
    DIAGNOSTICS("Diag"),
    SETTINGS("Ajustes"),
    WEB("Bolus AI"),
}

@Composable
fun BolusCompanionApp() {
    val context = LocalContext.current
    val settingsRepository = remember { AppSettingsRepository(context) }
    val logRepository = remember { HealthConnectLogRepository(context) }
    val queueRepository = remember { MealQueueRepository(context) }
    val bolusProfileRepository = remember { BolusProfileRepository(context) }
    val settings by settingsRepository.observe().collectAsState()
    val bolusProfile by bolusProfileRepository.observe().collectAsState()
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
                        CompanionScreen.BOLUS -> BolusScreen(settings, bolusProfileRepository, bolusProfile)
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
    var manualCarbs by remember { mutableStateOf("") }
    var manualProtein by remember { mutableStateOf("") }
    var manualFat by remember { mutableStateOf("") }
    var manualFiber by remember { mutableStateOf("") }
    var manualMessage by remember { mutableStateOf("") }
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
                OutlinedButton(onClick = { navigate(CompanionScreen.WEB) }) { Text("Bolus AI") }
            }
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Entrada directa", style = MaterialTheme.typography.titleMedium)
                    Text("Usar si MyFitnessPal no escribe en Salud Conectada")
                    SettingsTextField("HC", manualCarbs) { manualCarbs = it }
                    SettingsTextField("Proteina", manualProtein) { manualProtein = it }
                    SettingsTextField("Grasa", manualFat) { manualFat = it }
                    SettingsTextField("Fibra", manualFiber) { manualFiber = it }
                    Button(onClick = {
                        manualMessage = "Enviando"
                        scope.launch {
                            val record = manualNutritionRecord(
                                carbs = manualCarbs.parseDecimal(),
                                protein = manualProtein.parseDecimal(),
                                fat = manualFat.parseDecimal(),
                                fiber = manualFiber.parseDecimal(),
                            )
                            if ((record.carbohydratesGrams ?: 0.0) <= 0.0 &&
                                (record.proteinGrams ?: 0.0) <= 0.0 &&
                                (record.fatGrams ?: 0.0) <= 0.0 &&
                                (record.fiberGrams ?: 0.0) <= 0.0
                            ) {
                                manualMessage = "Introduce al menos un valor"
                                return@launch
                            }
                            val repository = MealQueueRepository(context)
                            val summary = repository.enqueueDetected(listOf(record))
                            val queuedHash = summary.queuedHashes.firstOrNull() ?: summary.updateHashes.firstOrNull()
                            val item = queuedHash?.let { repository.findByDedupeHash(it) }
                            if (item == null) {
                                manualMessage = "Ya estaba registrada"
                                return@launch
                            }
                            val due = listOf(item)
                            repository.markSending(due)
                            val result = NutritionIngestClient().send(
                                primaryUrl = settings.primaryUrl,
                                backupUrl = settings.backupUrl,
                                ingestKey = settings.ingestKey,
                                payloadJson = due.first().payloadJson,
                            )
                            if (result.ok) {
                                repository.markSent(due, result)
                                manualMessage = "Enviado a ${result.endpoint.name.lowercase()}"
                                manualCarbs = ""
                                manualProtein = ""
                                manualFat = ""
                                manualFiber = ""
                            } else {
                                repository.markRetry(due, result)
                                manualMessage = "Queda en cola para reintento"
                            }
                        }
                    }) { Text("Enviar comida") }
                    if (manualMessage.isNotBlank()) Text(manualMessage)
                }
            }
        }
    }
}

private fun manualNutritionRecord(
    carbs: Double?,
    protein: Double?,
    fat: Double?,
    fiber: Double?,
): NutritionRecordSnapshot {
    val now = Instant.now()
    return NutritionRecordSnapshot(
        metadataId = "manual-${now.toEpochMilli()}",
        sourcePackage = "org.bolusai.companion.manual",
        startTime = now,
        endTime = now,
        mealType = "manual",
        carbohydratesGrams = carbs,
        proteinGrams = protein,
        fatGrams = fat,
        fiberGrams = fiber,
        caloriesKcal = null,
    )
}

private fun String.parseDecimal(): Double? =
    trim()
        .replace(",", ".")
        .takeIf { it.isNotBlank() }
        ?.toDoubleOrNull()

@Composable
private fun BolusScreen(
    settings: AppSettings,
    profileRepository: BolusProfileRepository,
    profile: BolusProfile,
) {
    val scope = rememberCoroutineScope()
    var glucose by remember { mutableStateOf("") }
    var carbs by remember { mutableStateOf("") }
    var fiber by remember { mutableStateOf("") }
    var iob by remember { mutableStateOf("") }
    var slot by remember { mutableStateOf("lunch") }
    var message by remember { mutableStateOf("") }
    var result by remember { mutableStateOf<BolusCalculationResult?>(null) }
    val calculator = remember { BolusCalculator() }

    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Perfil local", style = MaterialTheme.typography.titleMedium)
                    Text("Usuario: ${profile.userId}")
                    Text("Actualizado: ${profile.updatedAt ?: "perfil por defecto"}")
                    if (!profile.isSynced()) Text("Sin perfil sincronizado: sincroniza ajustes antes de calcular.")
                    Text("DIA ${formatNumber(profile.diaHours)}h - redondeo ${formatUnits(profile.roundStepU)}")
                    Button(onClick = {
                        message = "Sincronizando ajustes"
                        scope.launch {
                            val sync = MobileBolusSettingsClient().sync(
                                primaryUrl = settings.primaryUrl,
                                backupUrl = settings.backupUrl,
                                ingestKey = settings.ingestKey,
                            )
                            if (sync.ok && sync.profile != null) {
                                profileRepository.save(sync.profile)
                                message = sync.message
                            } else {
                                message = sync.message
                            }
                        }
                    }) { Text("Sincronizar ajustes") }
                    if (message.isNotBlank()) Text(message)
                }
            }
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Calculadora offline", style = MaterialTheme.typography.titleMedium)
                    SlotSelector(slot) { slot = it }
                    SettingsTextField("Glucosa mg/dL", glucose) { glucose = it }
                    SettingsTextField("HC g", carbs) { carbs = it }
                    SettingsTextField("Fibra g", fiber) { fiber = it }
                    SettingsTextField("IOB manual U", iob) { iob = it }
                    Button(onClick = {
                        if (!profile.isSynced()) {
                            result = null
                            message = "Sincroniza ajustes antes de calcular."
                            return@Button
                        }
                        val input = BolusCalculationInput(
                            glucoseMgdl = glucose.parseDecimal(),
                            carbsG = carbs.parseDecimal() ?: 0.0,
                            fiberG = fiber.parseDecimal() ?: 0.0,
                            manualIobU = iob.parseDecimal() ?: 0.0,
                            slot = slot,
                        )
                        result = calculator.calculate(profile, input)
                    }) { Text("Calcular") }
                }
            }
        }
        result?.let { calculated ->
            item { BolusResultCard(calculated) }
        }
    }
}

@Composable
private fun SlotSelector(selected: String, onSelected: (String) -> Unit) {
    val labels = listOf(
        "breakfast" to "Desayuno",
        "lunch" to "Comida",
        "dinner" to "Cena",
        "snack" to "Extra",
    )
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        labels.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { (value, label) ->
                    if (selected == value) {
                        Button(onClick = { onSelected(value) }, modifier = Modifier.weight(1f)) { Text(label) }
                    } else {
                        OutlinedButton(onClick = { onSelected(value) }, modifier = Modifier.weight(1f)) { Text(label) }
                    }
                }
            }
        }
    }
}

@Composable
private fun BolusResultCard(result: BolusCalculationResult) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Resultado", style = MaterialTheme.typography.titleMedium)
            Text("${formatUnits(result.finalBolusU)} ahora", style = MaterialTheme.typography.headlineSmall)
            Text("Comida ${formatUnits(result.mealBolusU)} - correccion ${formatUnits(result.correctionBolusU)} - IOB ${formatUnits(result.manualIobU)}")
            Text("HC netos ${formatNumber(result.netCarbsG)}g - objetivo ${formatNumber(result.targetMgdl)} mg/dL")
            result.warnings.forEach { warning -> Text(warning) }
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
    var mfpSearch by remember { mutableStateOf("") }
    var mfpAssistMessage by remember { mutableStateOf("") }
    var hasMfpAccessibility by remember { mutableStateOf(isMyFitnessPalAssistantEnabled(context)) }
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
                Text("Automatizacion MyFitnessPal")
                Switch(
                    checked = settings.nutritionSyncEnabled,
                    onCheckedChange = { enabled -> repository.setNutritionSyncEnabled(enabled) },
                )
            }
        }
        item { Text("Modo: MyFitnessPal por Hermes. Health Connect no se usa para MyFitnessPal.") }
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
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Asistente MyFitnessPal", style = MaterialTheme.typography.titleMedium)
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Experimental")
                        Switch(
                            checked = settings.myFitnessPalAssistEnabled,
                            onCheckedChange = { enabled -> repository.setMyFitnessPalAssistEnabled(enabled) },
                        )
                    }
                    Text(if (hasMfpAccessibility) "Accesibilidad concedida" else "Falta activar el servicio de accesibilidad")
                    Button(onClick = {
                        context.startActivity(MyFitnessPalAssistantService.settingsIntent())
                        hasMfpAccessibility = isMyFitnessPalAssistantEnabled(context)
                    }) { Text("Abrir Accesibilidad") }
                    SettingsTextField("Buscar alimento", mfpSearch) { mfpSearch = it }
                    Button(
                        enabled = settings.myFitnessPalAssistEnabled,
                        onClick = {
                            hasMfpAccessibility = isMyFitnessPalAssistantEnabled(context)
                            mfpAssistMessage = when {
                                !hasMfpAccessibility -> "Activa primero el servicio de accesibilidad"
                                mfpSearch.isBlank() -> "Escribe un alimento"
                                MyFitnessPalAssistantService.startSearch(context, mfpSearch) -> "Abriendo MyFitnessPal"
                                else -> "No hay deep link confirmado para busqueda textual"
                            }
                        },
                    ) { Text("Probar busqueda") }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = {
                            mfpAssistMessage = if (MyFitnessPalAssistantService.openDiary(context)) {
                                "Abriendo diario"
                            } else {
                                "MyFitnessPal no acepta diario"
                            }
                        }) { Text("Abrir diario") }
                        OutlinedButton(onClick = {
                            mfpAssistMessage = if (MyFitnessPalAssistantService.openBarcodeScanner(context)) {
                                "Abriendo escaner"
                            } else {
                                "MyFitnessPal no acepta escaner"
                            }
                        }) { Text("Escaner") }
                    }
                    if (mfpAssistMessage.isNotBlank()) Text(mfpAssistMessage)
                }
            }
        }
    }
}

private fun isMyFitnessPalAssistantEnabled(context: android.content.Context): Boolean {
    val manager = context.getSystemService(AccessibilityManager::class.java) ?: return false
    return manager.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
        .any { it.resolveInfo.serviceInfo.packageName == context.packageName && it.resolveInfo.serviceInfo.name.endsWith("MyFitnessPalAssistantService") }
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
        item { Text("Automatizacion MyFitnessPal: ${if (settings.nutritionSyncEnabled) "ON" else "OFF"}") }
        item { Text("Cola: ${queueItems.size} elementos - ultimo endpoint: ${last?.endpointUsed ?: "-"}") }
        item { Text("Ultimo error: ${last?.lastError ?: "-"}") }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Eventos recientes", style = MaterialTheme.typography.titleMedium)
                    if (logs.isEmpty()) {
                        Text("Sin eventos registrados")
                    } else {
                        logs.take(8).forEach { log ->
                            Text("${formatInstantMillis(log.createdAt.toEpochMilli())} ${log.status} ${log.record.mealType ?: log.record.sourcePackage}")
                            if (!log.backendResponseSanitized.isNullOrBlank()) {
                                Text(log.backendResponseSanitized.take(180))
                            }
                        }
                    }
                }
            }
        }
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
    LaunchedEffect(settings.primaryUrl) {
        launcher.open(settings.primaryUrl)
    }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Bolus AI", style = MaterialTheme.typography.titleMedium)
        Text("Abriendo Bolus AI en Chrome para permitir la conexion Bluetooth de la bascula.")
        Button(onClick = { launcher.open(settings.primaryUrl) }) { Text("Abrir de nuevo") }
    }
}

private fun macros(item: MealQueueItem): String =
    "HC ${item.carbohydratesGrams ?: 0.0}g - P ${item.proteinGrams ?: 0.0}g - G ${item.fatGrams ?: 0.0}g - Fibra ${item.fiberGrams ?: 0.0}g - kcal ${item.caloriesKcal ?: 0.0}"

private fun formatInstant(value: String): String =
    runCatching { formatInstantMillis(Instant.parse(value).toEpochMilli()) }.getOrDefault(value)

private fun formatInstantMillis(value: Long): String =
    DateTimeFormatter.ofPattern("dd/MM HH:mm")
        .format(Instant.ofEpochMilli(value).atZone(ZoneId.systemDefault()))

private fun formatNumber(value: Double): String =
    String.format(Locale.US, "%.1f", value)

private fun formatUnits(value: Double): String =
    "${formatNumber(value)} U"
