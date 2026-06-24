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
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.ArrowForward
import androidx.compose.material.icons.outlined.CameraAlt
import androidx.compose.material.icons.outlined.Calculate
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Cloud
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.GridView
import androidx.compose.material.icons.outlined.MedicalInformation
import androidx.compose.material.icons.outlined.Restaurant
import androidx.compose.material.icons.outlined.RestaurantMenu
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Sync
import androidx.compose.material.icons.outlined.Wifi
import androidx.compose.material.icons.outlined.WifiOff
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
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
import org.bolusai.companion.dexcom.DexcomEventWriter
import org.bolusai.companion.health.HealthConnectAvailability
import org.bolusai.companion.health.HealthConnectState
import org.bolusai.companion.health.HealthPermissions
import org.bolusai.companion.network.ActiveEndpoint
import org.bolusai.companion.network.NutritionIngestClient
import org.bolusai.companion.network.ServerStatus
import org.bolusai.companion.network.ServerStatusClient
import org.bolusai.companion.portal.PortalGroup
import org.bolusai.companion.portal.InAppPortal
import org.bolusai.companion.portal.portalDestinations
import org.bolusai.companion.queue.MealQueueItem
import org.bolusai.companion.queue.MealQueueRepository
import org.bolusai.companion.scale.ProzisScaleManager
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
import org.bolusai.companion.ui.theme.BolusAiTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NutritionSyncScheduler.schedule(this)
        setContent { BolusCompanionApp() }
    }
}

private enum class CompanionScreen(val label: String) {
    HOME("Inicio"),
    PORTAL_MENU("Menú"),
    BOLUS("Bolo"),
    MEALS("Comidas"),
    DIAGNOSTICS("Estado"),
    SETTINGS("Más"),
    SCALE("Báscula"),
    WEB("Bolus AI"),
}

private val primaryScreens = listOf(
    CompanionScreen.HOME,
    CompanionScreen.PORTAL_MENU,
    CompanionScreen.BOLUS,
    CompanionScreen.SETTINGS,
)

private val expandedScreens = listOf(
    CompanionScreen.HOME,
    CompanionScreen.PORTAL_MENU,
    CompanionScreen.BOLUS,
    CompanionScreen.MEALS,
    CompanionScreen.DIAGNOSTICS,
    CompanionScreen.SETTINGS,
)

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
    var screen by remember { mutableStateOf(CompanionScreen.WEB) }
    var portalRoute by remember { mutableStateOf("#/") }

    LaunchedEffect(settings.nutritionSyncEnabled, settings.dexcomWriteEnabled) {
        if (settings.nutritionSyncEnabled || settings.dexcomWriteEnabled) {
            NutritionActiveSyncService.start(context)
        } else {
            NutritionActiveSyncService.stop(context)
        }
    }

    BolusAiTheme {
        if (screen == CompanionScreen.WEB) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .statusBarsPadding()
                        .background(MaterialTheme.colorScheme.surface)
                        .padding(horizontal = 8.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier
                            .size(34.dp)
                            .clip(RoundedCornerShape(10.dp))
                            .background(
                                Brush.linearGradient(
                                    listOf(
                                        MaterialTheme.colorScheme.primary,
                                        MaterialTheme.colorScheme.secondary,
                                    ),
                                ),
                            ),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text("B", color = Color.White, fontWeight = FontWeight.Bold)
                    }
                    Text(
                        "Bolus AI",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.weight(1f),
                    )
                    IconButton(onClick = { screen = CompanionScreen.PORTAL_MENU }) {
                        Icon(Icons.Outlined.GridView, contentDescription = "Todas las funciones")
                    }
                    IconButton(onClick = { screen = CompanionScreen.SETTINGS }) {
                        Icon(Icons.Outlined.Settings, contentDescription = "Integraciones Android")
                    }
                }
                Box(Modifier.weight(1f)) {
                    WebScreen(
                        settings = settings,
                        route = portalRoute,
                        onOpenScale = { screen = CompanionScreen.SCALE },
                    )
                }
            }
        } else {
            BoxWithConstraints(Modifier.fillMaxSize()) {
                val expanded = maxWidth >= 600.dp
                Scaffold(
                    containerColor = MaterialTheme.colorScheme.background,
                    topBar = { AppHeader(screen.label) },
                    bottomBar = {
                        if (!expanded) {
                            AppBottomNavigation(screen) { screen = it }
                        }
                    },
                ) { innerPadding ->
                    Row(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(innerPadding),
                    ) {
                        if (expanded) {
                            AppNavigationRail(screen) { screen = it }
                        }
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .fillMaxSize()
                                .padding(horizontal = 16.dp, vertical = 14.dp),
                            contentAlignment = Alignment.TopCenter,
                        ) {
                            Box(
                                modifier = Modifier
                                    .fillMaxSize()
                                    .widthIn(max = if (expanded) 1100.dp else 680.dp),
                            ) {
                                when (screen) {
                                    CompanionScreen.HOME -> HomeScreen(settings, queueItems) { screen = it }
                                    CompanionScreen.PORTAL_MENU -> PortalMenuScreen(settings) { route ->
                                        if (route == "#/scale") {
                                            screen = CompanionScreen.SCALE
                                        } else {
                                            portalRoute = route
                                            screen = CompanionScreen.WEB
                                        }
                                    }
                                    CompanionScreen.BOLUS -> BolusScreen(settings, bolusProfileRepository, bolusProfile)
                                    CompanionScreen.MEALS -> MealsScreen(queueItems)
                                    CompanionScreen.DIAGNOSTICS -> DiagnosticsScreen(
                                        settings,
                                        logs,
                                        queueItems,
                                        logRepository,
                                        queueRepository,
                                    )
                                    CompanionScreen.SETTINGS -> SettingsScreen(
                                        settings,
                                        settingsRepository,
                                        onBackToBolusAi = { screen = CompanionScreen.WEB },
                                        onOpenMeals = { screen = CompanionScreen.MEALS },
                                        onOpenDiagnostics = { screen = CompanionScreen.DIAGNOSTICS },
                                    ) { route ->
                                        if (route == "#/scale") {
                                            screen = CompanionScreen.SCALE
                                        } else {
                                            portalRoute = route
                                            screen = CompanionScreen.WEB
                                        }
                                    }
                                    CompanionScreen.SCALE -> ScaleScreen { screen = CompanionScreen.WEB }
                                    CompanionScreen.WEB -> Unit
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AppHeader(section: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = 18.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(
                    Brush.linearGradient(
                        listOf(MaterialTheme.colorScheme.primary, MaterialTheme.colorScheme.secondary),
                    ),
                ),
            contentAlignment = Alignment.Center,
        ) {
            Text("B", color = Color.White, fontWeight = FontWeight.Bold)
        }
        Column {
            Text("Bolus AI", style = MaterialTheme.typography.titleMedium)
            Text(
                section,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun AppBottomNavigation(
    selected: CompanionScreen,
    onSelected: (CompanionScreen) -> Unit,
) {
    NavigationBar(containerColor = MaterialTheme.colorScheme.surface, tonalElevation = 6.dp) {
        primaryScreens.forEach { item ->
            NavigationBarItem(
                selected = selected == item,
                onClick = { onSelected(item) },
                label = { Text(item.label) },
                icon = { Icon(screenIcon(item), contentDescription = item.label) },
            )
        }
    }
}

@Composable
private fun AppNavigationRail(
    selected: CompanionScreen,
    onSelected: (CompanionScreen) -> Unit,
) {
    Column(
        modifier = Modifier
            .widthIn(min = 104.dp, max = 104.dp)
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.surface)
            .padding(vertical = 16.dp, horizontal = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        expandedScreens.forEach { item ->
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onSelected(item) },
                color = if (selected == item) {
                    MaterialTheme.colorScheme.secondaryContainer
                } else {
                    Color.Transparent
                },
                shape = RoundedCornerShape(16.dp),
            ) {
                Column(
                    modifier = Modifier.padding(vertical = 12.dp, horizontal = 6.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Icon(screenIcon(item), contentDescription = item.label)
                    Text(item.label, style = MaterialTheme.typography.labelMedium)
                }
            }
        }
    }
}

private fun screenIcon(screen: CompanionScreen) = when (screen) {
    CompanionScreen.HOME -> Icons.Outlined.Home
    CompanionScreen.PORTAL_MENU -> Icons.Outlined.GridView
    CompanionScreen.BOLUS -> Icons.Outlined.Calculate
    CompanionScreen.MEALS -> Icons.Outlined.Restaurant
    CompanionScreen.DIAGNOSTICS -> Icons.Outlined.MedicalInformation
    CompanionScreen.SETTINGS -> Icons.Outlined.Settings
    CompanionScreen.SCALE -> Icons.Outlined.RestaurantMenu
    CompanionScreen.WEB -> Icons.Outlined.Cloud
}

@Composable
private fun PortalMenuScreen(settings: AppSettings, onOpenRoute: (String) -> Unit) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text(
                "Todo Bolus AI",
                style = MaterialTheme.typography.titleLarge,
            )
            Text(
                "Las funciones web se abren contra el NAS o Render según disponibilidad.",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        PortalGroup.entries.forEach { group ->
            item {
                Text(
                    group.title,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            items(
                items = portalDestinations.filter { it.group == group },
                key = { it.route },
            ) { destination ->
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                    elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
                    onClick = { onOpenRoute(destination.route) },
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(destination.title, style = MaterialTheme.typography.titleMedium)
                            Text(
                                destination.subtitle,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        Text(
                            "›",
                            color = MaterialTheme.colorScheme.primary,
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
    var showManualEntry by remember { mutableStateOf(false) }
    val statusClient = remember { ServerStatusClient() }
    val pendingCount = queueItems.count { it.status.name in setOf("QUEUED", "SENDING", "FAILED", "NEEDS_RETRY") }
    val lastMeal = queueItems.maxByOrNull { it.updatedAt }

    LaunchedEffect(settings.primaryUrl, settings.backupUrl) {
        serverStatus = statusClient.resolve(settings.primaryUrl, settings.backupUrl)
    }

    LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            DashboardHero(
                serverStatus = serverStatus,
                pendingCount = pendingCount,
                nutritionEnabled = settings.nutritionSyncEnabled,
            )
        }
        item {
            Text("Acciones rápidas", style = MaterialTheme.typography.titleMedium)
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                QuickActionCard(
                    title = "Todo Bolus AI",
                    subtitle = "Abrir funciones",
                    icon = Icons.Outlined.GridView,
                    modifier = Modifier.weight(1f),
                ) { navigate(CompanionScreen.PORTAL_MENU) }
                QuickActionCard(
                    title = "Sincronizar",
                    subtitle = if (pendingCount > 0) "$pendingCount pendientes" else "Todo al día",
                    icon = Icons.Outlined.Sync,
                    modifier = Modifier.weight(1f),
                ) {
                    syncMessage = "Sincronizando"
                    scope.launch {
                        val result = NutritionSyncRunner(context).run()
                        syncMessage = result.message
                    }
                }
            }
        }
        item {
            LastMealCard(lastMeal)
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                OutlinedButton(
                    onClick = { navigate(CompanionScreen.DIAGNOSTICS) },
                    modifier = Modifier.weight(1f),
                ) { Text("Estado y diagnóstico") }
                OutlinedButton(
                    onClick = { navigate(CompanionScreen.SETTINGS) },
                    modifier = Modifier.weight(1f),
                ) { Text("Integraciones") }
            }
        }
        item {
            TextButton(
                onClick = { showManualEntry = !showManualEntry },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (showManualEntry) "Ocultar entrada manual" else "Añadir comida manualmente")
            }
        }
        if (showManualEntry) item {
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

@Composable
private fun DashboardHero(
    serverStatus: ServerStatus,
    pendingCount: Int,
    nutritionEnabled: Boolean,
) {
    val online = serverStatus.activeEndpoint != ActiveEndpoint.NONE
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
        shape = RoundedCornerShape(26.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(
                    Brush.linearGradient(listOf(Color(0xFF0B5F9E), Color(0xFF008E88))),
                )
                .padding(20.dp),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            "Tu sistema está ${if (online) "listo" else "sin conexión"}",
                            color = Color.White,
                            style = MaterialTheme.typography.headlineSmall,
                        )
                        Text(
                            when (serverStatus.activeEndpoint) {
                                ActiveEndpoint.PRIMARY -> "Conectado al NAS principal"
                                ActiveEndpoint.BACKUP -> "Funcionando desde Render"
                                ActiveEndpoint.NONE -> "Los datos nuevos quedarán en cola"
                            },
                            color = Color.White.copy(alpha = 0.82f),
                        )
                    }
                    Box(
                        modifier = Modifier
                            .size(48.dp)
                            .clip(CircleShape)
                            .background(Color.White.copy(alpha = 0.16f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            if (online) Icons.Outlined.Wifi else Icons.Outlined.WifiOff,
                            contentDescription = null,
                            tint = Color.White,
                        )
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    HeroBadge(if (nutritionEnabled) "MyFitnessPal activo" else "Sync desactivado")
                    HeroBadge(if (pendingCount == 0) "Sin pendientes" else "$pendingCount pendientes")
                }
            }
        }
    }
}

@Composable
private fun HeroBadge(text: String) {
    Surface(color = Color.White.copy(alpha = 0.15f), shape = RoundedCornerShape(50)) {
        Text(
            text,
            modifier = Modifier.padding(horizontal = 11.dp, vertical = 6.dp),
            color = Color.White,
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

@Composable
private fun QuickActionCard(
    title: String,
    subtitle: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Card(
        modifier = modifier.clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(38.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            }
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(
                subtitle,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun LastMealCard(lastMeal: MealQueueItem?) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Última comida", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                if (lastMeal != null) {
                    Surface(
                        color = MaterialTheme.colorScheme.secondaryContainer,
                        shape = RoundedCornerShape(50),
                    ) {
                        Text(
                            "Enviada",
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                            style = MaterialTheme.typography.labelMedium,
                        )
                    }
                }
            }
            if (lastMeal == null) {
                Text("Aún no hay comidas detectadas.")
            } else {
                Text(formatInstant(lastMeal.startTime), fontWeight = FontWeight.SemiBold)
                Text(macros(lastMeal), color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(
                    "Sincronizada ${formatInstantMillis(lastMeal.updatedAt)}",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
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
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(body, style = MaterialTheme.typography.headlineSmall)
            Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun ScaleScreen(onBackToBolusAi: () -> Unit) {
    val context = LocalContext.current
    val manager = remember { ProzisScaleManager(context) }
    val scale by manager.state.collectAsState()
    val bluetoothPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { grants ->
        if (grants.values.all { it }) manager.connect()
    }

    fun connectWithPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val permissions = arrayOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT,
            )
            val missing = permissions.filter {
                ContextCompat.checkSelfPermission(context, it) != PackageManager.PERMISSION_GRANTED
            }
            if (missing.isNotEmpty()) {
                bluetoothPermissionLauncher.launch(missing.toTypedArray())
                return
            }
        }
        manager.connect()
    }

    DisposableEffect(Unit) {
        onDispose { manager.disconnect() }
    }

    LazyColumn(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            OutlinedButton(
                onClick = onBackToBolusAi,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Outlined.ArrowBack, contentDescription = null)
                Spacer(Modifier.size(8.dp))
                Text("Volver a Bolus AI")
            }
        }
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(26.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
            ) {
                Column(
                    modifier = Modifier.padding(22.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(58.dp)
                            .clip(CircleShape)
                            .background(
                                if (scale.connected) {
                                    MaterialTheme.colorScheme.secondaryContainer
                                } else {
                                    MaterialTheme.colorScheme.surfaceVariant
                                },
                            ),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            Icons.Outlined.RestaurantMenu,
                            contentDescription = null,
                            tint = if (scale.connected) {
                                MaterialTheme.colorScheme.secondary
                            } else {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            },
                        )
                    }
                    Text(
                        if (scale.connected) "${scale.grams} g" else "Báscula Prozis",
                        style = MaterialTheme.typography.headlineMedium,
                    )
                    Text(
                        scale.message,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (scale.connected) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            HeroBadge(if (scale.stable) "Peso estable" else "En movimiento")
                            scale.batteryPercent?.let { HeroBadge("Batería $it%") }
                        }
                    }
                }
            }
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Button(
                    onClick = {
                        if (scale.connected) manager.disconnect() else connectWithPermission()
                    },
                    enabled = !scale.connecting && !scale.scanning,
                    modifier = Modifier.weight(1f),
                ) {
                    Text(
                        when {
                            scale.scanning -> "Buscando…"
                            scale.connecting -> "Conectando…"
                            scale.connected -> "Desconectar"
                            else -> "Conectar báscula"
                        },
                    )
                }
                OutlinedButton(
                    onClick = manager::tare,
                    enabled = scale.connected,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("Tarar")
                }
            }
        }
        item {
            Text(
                "La báscula se conecta directamente desde Android. No depende del navegador ni del servidor.",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
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
private fun SettingsScreen(
    settings: AppSettings,
    repository: AppSettingsRepository,
    onBackToBolusAi: () -> Unit,
    onOpenMeals: () -> Unit,
    onOpenDiagnostics: () -> Unit,
    onOpenRoute: (String) -> Unit,
) {
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
    var dexcomTestMessage by remember { mutableStateOf("") }
    val dexcomAvailable = remember { DexcomEventWriter.isCompatibleDexcomInstalled(context) }
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
        item {
            OutlinedButton(
                onClick = onBackToBolusAi,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Outlined.ArrowBack, contentDescription = null)
                Spacer(Modifier.size(8.dp))
                Text("Volver a Bolus AI")
            }
        }
        item {
            Text("Ajustes", style = MaterialTheme.typography.titleLarge)
            Text(
                "Configuración general de Bolus AI e integraciones específicas de Android.",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        item {
            Button(onClick = { onOpenRoute("#/settings") }) {
                Text("Abrir ajustes generales de Bolus AI")
            }
        }
        item {
            Text(
                "Integraciones Android",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                OutlinedButton(onClick = onOpenMeals, modifier = Modifier.weight(1f)) {
                    Text("Comidas importadas")
                }
                OutlinedButton(onClick = onOpenDiagnostics, modifier = Modifier.weight(1f)) {
                    Text("Diagnóstico")
                }
            }
        }
        item { SettingsTextField("Servidor principal", primary) { primary = it } }
        item { Button(onClick = { repository.updatePrimaryUrl(primary) }) { Text("Guardar principal") } }
        item { SettingsTextField("Servidor backup", backup) { backup = it } }
        item { Button(onClick = { repository.updateBackupUrl(backup) }) { Text("Guardar backup") } }
        item {
            OutlinedTextField(
                value = ingestKey,
                onValueChange = { ingestKey = it },
                label = { Text("Clave de integración") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
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
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Dexcom G7 modificada", style = MaterialTheme.typography.titleMedium)
                    if (!dexcomAvailable) {
                        Text(
                            "No está instalada en este dispositivo.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Escribir bolos en Dexcom G7 modificada", modifier = Modifier.weight(1f))
                        Switch(
                            checked = settings.dexcomWriteEnabled,
                            enabled = dexcomAvailable,
                            onCheckedChange = { enabled ->
                                repository.setDexcomWriteEnabled(enabled)
                                dexcomTestMessage = ""
                            },
                        )
                    }
                    Button(
                        enabled = settings.dexcomWriteEnabled && dexcomAvailable,
                        onClick = {
                            val sent = DexcomEventWriter.sendInsulinEvent(
                                context = context,
                                insulinUnits = 5.5,
                            )
                            dexcomTestMessage = if (sent) {
                                "Bolo de prueba 5.5U enviado."
                            } else {
                                "No se pudo enviar el bolo de prueba."
                            }
                        },
                    ) { Text("Enviar bolo de prueba 5.5U") }
                    if (dexcomTestMessage.isNotBlank()) Text(dexcomTestMessage)
                }
            }
        }
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
private fun WebScreen(
    settings: AppSettings,
    route: String,
    onOpenScale: () -> Unit,
) {
    InAppPortal(
        settings = settings,
        route = route,
        onOpenNativeScale = onOpenScale,
    )
}

private fun macros(item: MealQueueItem): String =
    "HC ${formatNumber(item.carbohydratesGrams ?: 0.0)}g · " +
        "P ${formatNumber(item.proteinGrams ?: 0.0)}g · " +
        "G ${formatNumber(item.fatGrams ?: 0.0)}g · " +
        "Fibra ${formatNumber(item.fiberGrams ?: 0.0)}g · " +
        "${formatNumber(item.caloriesKcal ?: 0.0)} kcal"

private fun formatInstant(value: String): String =
    runCatching { formatInstantMillis(Instant.parse(value).toEpochMilli()) }.getOrDefault(value)

private fun formatInstantMillis(value: Long): String =
    DateTimeFormatter.ofPattern("dd/MM HH:mm")
        .format(Instant.ofEpochMilli(value).atZone(ZoneId.systemDefault()))

private fun formatNumber(value: Double): String =
    String.format(Locale.US, "%.1f", value)

private fun formatUnits(value: Double): String =
    "${formatNumber(value)} U"
