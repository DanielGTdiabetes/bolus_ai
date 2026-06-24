package org.bolusai.companion.portal

data class PortalDestination(
    val title: String,
    val subtitle: String,
    val route: String,
    val group: PortalGroup,
)

enum class PortalGroup(val title: String) {
    DAILY("Uso diario"),
    FOOD("Comida y visión"),
    INSIGHTS("Seguimiento"),
    ACCOUNT("Cuenta y sistema"),
}

val portalDestinations = listOf(
    PortalDestination("Inicio", "Glucosa, IOB, COB y acciones rápidas", "#/", PortalGroup.DAILY),
    PortalDestination("Escanear", "Cámara, galería, peso y estimación", "#/scan", PortalGroup.DAILY),
    PortalDestination("Calcular bolo", "Cálculo completo conectado al backend", "#/bolus", PortalGroup.DAILY),
    PortalDestination("Asistente basal", "Registro, análisis y recomendaciones", "#/basal", PortalGroup.DAILY),
    PortalDestination("Predicción", "Evolución estimada de glucosa", "#/forecast", PortalGroup.DAILY),
    PortalDestination("Historial", "Bolos, comidas y tratamientos", "#/history", PortalGroup.DAILY),

    PortalDestination("Modo restaurante", "Carta, platos y comparación acumulada", "#/restaurant", PortalGroup.FOOD),
    PortalDestination("Báscula", "Conexión Bluetooth y pesaje", "#/scale", PortalGroup.FOOD),
    PortalDestination("Base de alimentos", "Consulta de alimentos y macros", "#/food-db", PortalGroup.FOOD),
    PortalDestination("Mis platos", "Favoritos y biblioteca personal", "#/favorites", PortalGroup.FOOD),

    PortalDestination("Aprendizaje", "Patrones y absorción de comidas", "#/learning", PortalGroup.INSIGHTS),
    PortalDestination("Sugerencias", "Recomendaciones generadas por Bolus AI", "#/suggestions", PortalGroup.INSIGHTS),
    PortalDestination("Mapa corporal", "Rotación de zonas de inyección", "#/bodymap", PortalGroup.INSIGHTS),
    PortalDestination("Notificaciones", "Alertas y avisos pendientes", "#/notifications", PortalGroup.INSIGHTS),
    PortalDestination("Suministros", "Agujas, sensores y existencias", "#/supplies", PortalGroup.INSIGHTS),

    PortalDestination("Mi perfil", "Perfil clínico y datos personales", "#/profile", PortalGroup.ACCOUNT),
    PortalDestination("Ajustes Bolus AI", "Cálculo, visión, Nightscout y alertas", "#/settings", PortalGroup.ACCOUNT),
    PortalDestination("Nightscout", "Configuración y estado de conexión", "#/nightscout-settings", PortalGroup.ACCOUNT),
    PortalDestination("Estado del sistema", "Servicios, base de datos y conectividad", "#/status", PortalGroup.ACCOUNT),
    PortalDestination("Calculadora de emergencia", "Cálculo manual de contingencia", "#/manual", PortalGroup.ACCOUNT),
)

fun buildPortalUrl(baseUrl: String, route: String): String =
    "${baseUrl.trimEnd('/')}/${route.removePrefix("/")}"
