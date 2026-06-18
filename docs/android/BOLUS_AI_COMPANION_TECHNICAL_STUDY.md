# Estudio técnico: Bolus AI Companion para Android

Fecha del estudio: 2026-06-18

## 1. Resumen ejecutivo

**Bolus AI Companion** es viable como APK Android híbrida: una app nativa mínima en Kotlin/Jetpack Compose que actúa como puerta de entrada a Bolus AI y como puente de integración nutricional con Health Connect. La decisión recomendada es **app nativa híbrida + TWA para abrir Bolus AI**, con fallback ordenado **TWA → Custom Tabs → WebView endurecido**. WebView debe ser siempre la última opción, solo para dispositivos o escenarios donde TWA/Custom Tabs no sean viables.

La integración nutricional debe sustituir el flujo iOS actual:

```text
MyFitnessPal → Apple Salud → Atajo iOS → AutoExport JSON → POST Bolus AI
```

por este flujo Android:

```text
MyFitnessPal → Health Connect → Bolus AI Companion → POST Bolus AI
```

El backend ya ofrece un endpoint compatible con ingesta flexible:

```text
POST /api/integrations/nutrition
```

con autenticación por JWT o por clave `NUTRITION_INGEST_SECRET`/`NUTRITION_INGEST_KEY`, aceptando `Authorization: Bearer <token>`, `X-Ingest-Key` o `?key=...`.

El backend también tiene endpoints de health suficientes para failover:

```text
GET /healthz
GET /api/health/check
```

Se recomienda que la app use `/healthz` como check rápido y `/api/health/check` como check extendido.

## 2. Viabilidad

### Viabilidad funcional

La app es viable porque:

- Health Connect expone `NutritionRecord` como tipo de datos de nutrición.
- MyFitnessPal ya se ha comprobado escribiendo nutrición en Health Connect.
- El backend acepta payloads planos y payloads tipo Health Auto Export, por lo que una APK puede enviar un JSON plano sin modificar backend.
- El formato funcional que Bolus AI necesita ya está validado por el flujo iOS actual; el trabajo pendiente en Android no es descubrir el contrato final del backend, sino comprobar cómo MyFitnessPal representa esos mismos datos dentro de Health Connect.
- Android permite lecturas en primer plano y, con permiso adicional, lecturas en segundo plano.
- WorkManager cubre sincronización periódica, reintentos y constraints de red.

### Viabilidad técnica

Stack recomendado:

- Kotlin.
- Jetpack Compose.
- MVVM o arquitectura por capas ligera.
- Health Connect Client.
- WorkManager.
- Retrofit + OkHttp.
- Room para cola, deduplicación y auditoría local.
- DataStore para ajustes no secretos.
- Android Keystore + EncryptedSharedPreferences o Jetpack Security para secretos.
- TWA mediante `android-browser-helper` para la experiencia web principal.

### Viabilidad de Play Store vs sideloading

- **Sideloading**: viable con menor fricción, siempre que el usuario instale la APK y conceda permisos Health Connect.
- **Play Store**: viable, pero exige justificar permisos de salud, política de privacidad, disclosure claro, finalidad limitada y aprobación de permisos Health Connect.

## 3. Arquitectura recomendada

### Decisión recomendada

**App nativa híbrida con Compose + TWA + módulo Health Connect.**

Motivo:

- TWA ofrece experiencia más cercana a app nativa para Bolus AI web, usando el runtime del navegador y manteniendo cookies/sesión del navegador.
- Compose permite pantallas nativas para Home, Ajustes, Diagnóstico, permisos y cola.
- Health Connect y WorkManager requieren lógica nativa; una PWA empaquetada no sería suficiente para sincronización robusta.
- La estrategia de portal debe priorizar **TWA**, después **Custom Tabs** y solo al final **WebView endurecido**, para reducir riesgos de seguridad y problemas de sesión.

### Diagrama lógico

```text
BolusAiCompanionApp
├─ UI Compose
│  ├─ Home
│  ├─ Settings
│  ├─ Diagnostics
│  ├─ HealthConnectLogs
│  └─ PendingQueue
├─ Portal
│  ├─ TwaLauncher
│  ├─ CustomTabsLauncher
│  └─ SafeWebViewFallback
├─ Health
│  ├─ HealthConnectAvailability
│  ├─ HealthPermissionManager
│  ├─ NutritionReader
│  └─ NutritionMapper
├─ Diagnostics
│  ├─ HealthConnectLogRepository
│  ├─ PipelineLogExporter
│  └─ SanitizedBackendResponseStore
├─ Bluetooth
│  ├─ DeviceScanner
│  ├─ DeviceLogs
│  ├─ DeviceSettings
│  └─ Providers
├─ Sync
│  ├─ NutritionSyncWorker
│  ├─ ManualSyncUseCase
│  ├─ FailoverResolver
│  └─ RetryPolicy
├─ Network
│  ├─ BolusApi
│  ├─ HealthApi
│  └─ AuthInterceptor
├─ Persistence
│  ├─ SettingsDataStore
│  ├─ SecretStore
│  ├─ RoomQueue
│  └─ DedupeStore
└─ Domain
   ├─ NutritionEvent
   ├─ SyncMode
   ├─ ServerStatus
   └─ PendingUpload
```

### Estructura de proyecto propuesta

```text
app/
├─ ui/
│  ├─ home/
│  ├─ settings/
│  ├─ diagnostics/
│  └─ components/
├─ portal/
│  ├─ TwaLauncher.kt
│  ├─ CustomTabsLauncher.kt
│  └─ SafeWebViewActivity.kt
├─ data/
│  ├─ db/
│  ├─ datastore/
│  └─ repository/
├─ health/
│  ├─ HealthConnectManager.kt
│  ├─ NutritionRecordReader.kt
│  ├─ NutritionRecordMapper.kt
│  └─ HealthPermissions.kt
├─ diagnostics/
│  ├─ HealthConnectLogEntity.kt
│  ├─ DiagnosticsRepository.kt
│  ├─ LogSanitizer.kt
│  └─ LogExporter.kt
├─ bluetooth/
│  ├─ DeviceScanner.kt
│  ├─ DeviceLogs.kt
│  ├─ DeviceSettings.kt
│  └─ providers/
│     └─ ProzisBitScaleProvider.kt
├─ network/
│  ├─ BolusApi.kt
│  ├─ ServerHealthClient.kt
│  └─ NetworkModule.kt
├─ sync/
│  ├─ NutritionSyncWorker.kt
│  ├─ SyncScheduler.kt
│  ├─ UploadQueueProcessor.kt
│  └─ FailoverPolicy.kt
├─ settings/
│  ├─ AppSettings.kt
│  └─ SettingsRepository.kt
├─ security/
│  ├─ SecretStore.kt
│  └─ UrlAllowlist.kt
└─ domain/
   ├─ NutritionEvent.kt
   ├─ UploadResult.kt
   ├─ ServerEndpoint.kt
   ├─ NutritionProvider.kt
   ├─ GlucoseProvider.kt
   ├─ ActivityProvider.kt
   ├─ DeviceProvider.kt
   └─ AiProvider.kt
```

## 4. Alternativas analizadas y descartadas

### Solo TWA

**Ventajas**:

- Muy buena experiencia web.
- Menor superficie nativa.
- Usa navegador actualizado.

**Descartada como única solución** porque no resuelve bien Health Connect, cola local, WorkManager, permisos, diagnóstico y sincronización nutricional.

### Solo WebView

**Ventajas**:

- Control total dentro de la app.
- Puede aparentar una app completamente nativa.

**Descartada como opción principal** por riesgos de seguridad, gestión de cookies/sesión separada, necesidad de endurecimiento estricto y peor compatibilidad con flujos web complejos.

### Custom Tabs

**Ventajas**:

- Seguro, simple, usa navegador.

**Descartada como experiencia principal** porque muestra interfaz de navegador y se siente menos nativo que TWA. Sí puede ser fallback aceptable.

### PWA empaquetada sin app nativa real

**Descartada** porque no cubre adecuadamente lectura periódica de Health Connect, cola local fiable y permisos nativos.

### Tasker + plugins

**Descartada para producto oficial** porque introduce dependencia externa, configuración frágil y peor mantenibilidad. Puede quedar como plan de emergencia o prototipo.

## 5. Permisos Android necesarios

### Permisos base

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
```

`POST_NOTIFICATIONS` aplica desde Android 13 para notificaciones de éxito/error.

### Health Connect

Permiso principal:

```xml
<uses-permission android:name="android.permission.health.READ_NUTRITION" />
```

Permisos opcionales según alcance:

```xml
<uses-permission android:name="android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND" />
<uses-permission android:name="android.permission.health.READ_HEALTH_DATA_HISTORY" />
```

Recomendación MVP:

- Fase 2/3: solicitar solo `READ_NUTRITION`.
- Fase 4: añadir `READ_HEALTH_DATA_IN_BACKGROUND` si el objetivo es sincronización automática real sin abrir la app.
- Evitar `READ_HEALTH_DATA_HISTORY` salvo que sea imprescindible importar más de 30 días previos.

### Foreground Service

No se recomienda para MVP salvo que se detecte que las lecturas manuales largas se interrumpen. Si se usa:

```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
```

El tipo exacto debe revisarse al implementar según target SDK y política vigente.

## 6. Limitaciones conocidas

### Health Connect

- `NutritionRecord` es intervalar y exige `startTime`, `endTime`, `mealType` y `metadata`.
- La disponibilidad de Health Connect depende de versión de Android, módulo instalado y fabricante.
- Las lecturas históricas de datos de otras apps pueden estar limitadas por defecto a 30 días desde la concesión de permisos.
- Las lecturas en segundo plano requieren permiso adicional.
- MyFitnessPal puede cambiar qué campos escribe o con qué granularidad agrupa comidas.
- Puede que Health Connect no incluya nombre de comida detallado; normalmente sí incluye `metadata` y origen de datos, pero no siempre un nombre legible.

### WorkManager

- No garantiza ejecución exacta al minuto.
- La periodicidad mínima práctica suele ser de unos 15 minutos.
- Fabricantes con políticas agresivas de batería pueden retrasar tareas.

### TWA

- Requiere relación de confianza por Digital Asset Links entre dominio y app.
- Requiere navegador compatible; Chrome 72+ es referencia.
- La app nativa no accede directamente a cookies/localStorage de la TWA.
- Para el dominio `duckdns.org` hay que validar que se puede alojar correctamente `/.well-known/assetlinks.json` en producción.

### WebView fallback

- Debe limitarse a dominios allowlist: `https://bolus-ai.duckdns.org` y `https://bolus-ai-1.onrender.com`.
- No debe usar `addJavascriptInterface` salvo necesidad extrema y contenido totalmente controlado.
- Debe bloquear navegación a dominios externos o abrirla en navegador externo.

## 7. Riesgos técnicos

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| MyFitnessPal deja de escribir NutritionRecord o cambia campos | Alto | Diagnóstico de registros crudos, tests con datos reales, fallback manual |
| Duplicados por relectura de ventanas temporales | Alto | Hash local estable + dedupe backend existente |
| WorkManager retrasado por batería | Medio | Modo manual, notificaciones, último sync visible |
| Health Connect sin permiso background | Medio | Sincronización manual y foreground reads |
| Render backup en cold start | Medio | Timeout diferenciado, health check previo, cola local |
| Backend devuelve `200` con `success:0` | Medio | Tratar respuesta semántica, no solo HTTP status |
| Cambios de políticas Play Store | Medio/Alto | Privacy policy, disclosure y minimización desde MVP |
| TWA no validada por Digital Asset Links | Medio | Fallback Custom Tab/WebView y checklist backend |

## 8. Riesgos de privacidad

- Los datos de nutrición son datos de salud o bienestar sensibles.
- La app debe explicar claramente que lee nutrición de Health Connect y la envía a Bolus AI.
- Debe existir un interruptor visible para activar/desactivar sincronización automática.
- Si está desactivada, no debe leer Health Connect ni programar workers.
- No deben guardarse datos médicos innecesarios; la cola local debe contener solo lo necesario para reintento.
- Los logs locales deben estar sanitizados: sin API key, sin JWT, sin payload completo salvo modo diagnóstico explícito.
- Debe existir opción para borrar cola, dedupe local y logs.
- Play Store exige uso limitado, beneficio claro para el usuario y política de privacidad completa.

## 9. Formato de datos propuesto

### Lectura desde Health Connect

Campos esperados desde `NutritionRecord`:

- `metadata.id` o identificador Health Connect.
- `metadata.dataOrigin.packageName` para detectar origen `com.myfitnesspal.android` si aplica.
- `startTime`.
- `endTime`.
- `mealType`.
- `totalCarbohydrate`.
- `protein`.
- `totalFat`.
- `dietaryFiber`.
- `energy`.
- Opcionales adicionales: azúcar, grasas saturadas, sodio, etc.

### Modelo dominio interno

```json
{
  "external_id": "healthconnect:<metadata.id>",
  "dedupe_hash": "sha256(source|start|end|carbs|protein|fat|fiber|calories)",
  "source": "MyFitnessPal",
  "source_package": "com.myfitnesspal.android",
  "meal_type": "LUNCH",
  "start_time": "2026-06-18T12:30:00Z",
  "end_time": "2026-06-18T12:45:00Z",
  "carbohydrates_total_g": 45.2,
  "protein_total_g": 22.0,
  "fat_total_g": 14.5,
  "fiber_total_g": 6.3,
  "calories_kcal": 410.0,
  "name": "MyFitnessPal meal",
  "app": "Bolus AI Companion Android",
  "provider": "Health Connect"
}
```

### Payload recomendado hacia backend actual

El backend actual ya normaliza estos nombres:

```json
{
  "date": "2026-06-18T12:30:00Z",
  "carbohydrates_total_g": 45.2,
  "protein_total_g": 22.0,
  "fat_total_g": 14.5,
  "fiber_total_g": 6.3,
  "calories_kcal": 410.0,
  "name": "MyFitnessPal meal",
  "source": "MyFitnessPal",
  "provider": "Health Connect",
  "origin": "Bolus AI Companion Android",
  "external_id": "healthconnect:<metadata.id>",
  "dedupe_hash": "sha256:...",
  "meal_type": "LUNCH"
}
```

Notas:

- El backend actual ignora algunos campos extra, pero son útiles para logs futuros.
- La deduplicación backend hoy se basa principalmente en timestamp/notas y macros. Como mejora futura, convendría almacenar `external_id` o `dedupe_hash` en `notes` o en una columna dedicada.
- Para compatibilidad inmediata, `date`, `carbohydrates_total_g`, `protein_total_g`, `fat_total_g` y `fiber_total_g` son los campos clave.

## 10. Endpoints necesarios

### Existentes y suficientes para MVP

```text
GET /healthz
```

Respuesta esperada actual:

```json
{"status":"ok","service":"bolus-ai"}
```

```text
GET /api/health/check
```

Respuesta esperada actual:

```json
{"status":"ok","direct":true,"emergency_mode":false}
```

```text
POST /api/integrations/nutrition
```

Autenticación aceptada:

```text
Authorization: Bearer <access_token>
X-Ingest-Key: <NUTRITION_INGEST_SECRET>
?key=<NUTRITION_INGEST_SECRET>
```

### Recomendación backend futura

Crear un endpoint estable específicamente para clientes móviles:

```text
GET /api/mobile/health
```

Respuesta propuesta:

```json
{
  "status": "ok",
  "service": "bolus-ai",
  "version": "0.1.0",
  "emergency_mode": false,
  "nutrition_ingest": "enabled",
  "server_time": "2026-06-18T10:00:00Z"
}
```

Y mejorar la ingesta con idempotencia explícita:

```text
POST /api/integrations/nutrition
Idempotency-Key: <dedupe_hash>
```

Respuesta propuesta:

```json
{
  "success": 1,
  "ingested_count": 1,
  "updated_count": 0,
  "duplicate_count": 0,
  "ids": ["..."]
}
```

## 11. Failover de servidor y principio “Never lose a meal”

URLs iniciales:

```text
Principal: https://bolus-ai.duckdns.org
Backup:    https://bolus-ai-1.onrender.com
```

Algoritmo recomendado:

1. Leer ajustes locales.
2. Comprobar `principal + /healthz` con timeout corto, por ejemplo 3 segundos.
3. Si `status=ok`, usar principal.
4. Si falla por timeout, TLS, HTTP no 2xx o JSON inválido, comprobar backup.
5. Si backup responde, usar backup y mostrar aviso discreto: `Usando servidor backup`.
6. Si ambos fallan, guardar envío en cola local.
7. Programar reintento con WorkManager y backoff exponencial.
8. Aplicar el principio **Never lose a meal**: no descartar ninguna comida aunque falle Internet, fallen ambos servidores, se reinicie el móvil o se cierre la aplicación.
9. Persistir cada comida en Room antes de intentar enviarla cuando el modo de envío requiera POST.
10. Reintentar desde Room hasta estado terminal `SENT` o `DUPLICATE` confirmado.

Estados UI:

- `Principal activo`.
- `Backup activo`.
- `Sin conexión: cola pendiente`.
- `No autenticado`.
- `Servidor en emergencia` si `/api/health/check` indica `emergency_mode=true`.

## 12. Sincronización nutricional

### Toggle obligatorio

Ajuste principal:

```text
Activar sincronización nutricional automática: ON/OFF
```

Reglas:

- OFF:
  - Cancelar workers.
  - No leer Health Connect.
  - No enviar datos.
  - Permitir opcionalmente mantener permisos concedidos, pero no usarlos.
- ON:
  - Verificar permisos.
  - Programar worker periódico si el modo es automático.
  - Permitir sincronización manual inmediata.

### Modos

1. **Manual**
   - Botón `Buscar comidas nuevas`.
   - Lee Health Connect solo por acción explícita.
   - Recomendado para Fase 2/3.

2. **Preguntar antes de enviar**
   - Lee registros nuevos.
   - Muestra lista de comidas pendientes.
   - Usuario confirma envío.
   - Recomendado para transición y depuración.

3. **Automático**
   - Worker periódico.
   - Envía directamente si hay permisos, red y toggle ON.
   - Recomendado cuando el mapeo esté validado con datos reales de MyFitnessPal.

### Detección de nuevas comidas

Estrategia recomendada:

- Mantener `lastSuccessfulReadEndTime`.
- Leer ventana solapada: desde `lastSuccessfulReadEndTime - 6 horas` hasta `now`.
- Filtrar por `dataOrigin.packageName` si MyFitnessPal está disponible.
- Generar `dedupe_hash` por registro.
- Si hash ya está en `dedupe_events`, ignorar.
- Si registro cambió con mismo `metadata.id` pero macros distintos, tratar como actualización y reenviar.

### Cola local persistente: Never lose a meal

Principio del proyecto: **nunca perder una comida**. La app debe asumir que Internet puede fallar, ambos servidores pueden caer, Android puede matar el proceso y el móvil puede reiniciarse. Por eso, todo registro aceptado para envío debe persistirse en Room antes del POST y conservarse hasta que exista confirmación segura de enviado o duplicado.

Tabla `pending_uploads`:

```text
id UUID
external_id TEXT nullable
dedupe_hash TEXT unique
payload_json TEXT
target_url TEXT nullable
status PENDING|SENDING|SENT|FAILED|NEEDS_CONFIRMATION
attempt_count INTEGER
last_error TEXT nullable
created_at Instant
updated_at Instant
next_retry_at Instant nullable
```

Tabla `dedupe_events`:

```text
dedupe_hash TEXT primary key
external_id TEXT nullable
source_package TEXT nullable
record_start Instant
record_end Instant
sent_at Instant nullable
backend_ids TEXT nullable
payload_fingerprint TEXT
```


## 13. Diagnostics & Logs / Health Connect Logs

Objetivo: mantener un historial local, sanitizado y exportable de todo el pipeline nutricional:

```text
MyFitnessPal
↓
Health Connect
↓
NutritionRecord leído
↓
JSON generado
↓
POST enviado
↓
Respuesta backend
```

Este módulo no sustituye la cola de envío: es una capa de auditoría local para depuración, validación de equivalencia Android vs iOS y soporte técnico. Debe estar disponible desde la pantalla `Diagnóstico` y desde una vista específica `Health Connect Logs`.

### Datos a guardar por evento

Guardar solo datos mínimos y sanitizados:

- `metadata.id`.
- `source_package` / `dataOrigin.packageName`.
- `startTime`.
- `endTime`.
- `mealType`.
- Carbohidratos.
- Proteína.
- Grasa.
- Fibra.
- Calorías.
- `dedupe_hash`.
- Endpoint utilizado: `principal`, `backup` o `none`.
- Estado: `detectado`, `pendiente`, `enviado`, `duplicado` o `error`.
- JSON generado para Bolus AI, sanitizado y limitado a campos nutricionales necesarios.
- Respuesta backend sanitizada: código HTTP, `success`, contadores, ids no sensibles si son necesarios y mensaje de error redactado.

Nunca guardar JWT, API keys, claves de ingesta, cookies, cabeceras completas de autenticación ni trazas con secretos.

### Acciones de usuario

La pantalla de diagnóstico debe permitir:

- Ver últimos registros leídos.
- Filtrar por estado, origen y endpoint usado.
- Exportar logs a JSON.
- Exportar logs a TXT legible.
- Borrar logs manualmente.
- Configurar retención: 7, 30 o 90 días.

### Reglas con sincronización desactivada

Si la sincronización nutricional está OFF:

- No leer Health Connect.
- No crear nuevos logs de `NutritionRecord`.
- No generar JSON nuevo.
- No programar workers de lectura.
- Sí se permite consultar, exportar o borrar logs ya existentes, porque son datos locales previos controlados por el usuario.

### Modelo local sugerido

Tabla `health_connect_logs`:

```text
id UUID primary key
metadata_id TEXT nullable
source_package TEXT nullable
start_time Instant
end_time Instant
meal_type TEXT nullable
carbs_g REAL nullable
protein_g REAL nullable
fat_g REAL nullable
fiber_g REAL nullable
calories_kcal REAL nullable
dedupe_hash TEXT
endpoint_used TEXT nullable
status DETECTED|PENDING|SENT|DUPLICATE|ERROR
generated_payload_json TEXT nullable
backend_response_sanitized TEXT nullable
created_at Instant
updated_at Instant
expires_at Instant nullable
```

La limpieza por retención puede ejecutarse con WorkManager, pero nunca debe borrar entradas `PENDING` o `FAILED` que sigan siendo necesarias para cumplir “Never lose a meal”; esos registros pertenecen a la cola operativa y solo se purgan cuando exista resolución segura.

## 14. Arquitectura desacoplada de providers futuros

No implementar en el MVP, pero diseñar el dominio para no acoplar Bolus AI Companion a una única fuente. Interfaces previstas:

```text
NutritionProvider
├── HealthConnectProvider
└── SamsungHealthProvider

GlucoseProvider
├── NightscoutProvider
├── DexcomProvider
├── xDripProvider
└── JugglucoProvider

ActivityProvider
├── HealthConnectProvider
└── GarminProvider

DeviceProvider
├── ProzisBitScaleProvider
└── FutureScaleProvider

AiProvider
└── HermesProvider
```

Cada provider debe exponer capacidades, permisos requeridos, estado de conexión, última lectura y errores sanitizados. La UI debe consumir casos de uso de dominio, no SDKs concretos.

## 15. Bluetooth Services futuros

Android no debe heredar la limitación iOS basada en Bluefy/Web Bluetooth. **La comunicación BLE nunca debe depender de Web Bluetooth ni de navegadores.** Toda integración BLE debe ser nativa en Kotlin usando APIs Bluetooth LE de Android.

Arquitectura futura:

```text
Bluetooth
├── DeviceScanner
├── DeviceLogs
├── DeviceSettings
└── Providers
    └── ProzisBitScaleProvider
```

Provider inicial propuesto: `ProzisBitScaleProvider`. Objetivos futuros:

- Escaneo BLE.
- Reconexión.
- Lectura de batería.
- Peso actual.
- Detección de estabilidad del peso.
- Logs y diagnóstico BLE.
- Botón `usar peso` para enviar el peso estable al contexto de Bolus AI.

## 16. Seguridad

### Secretos

Opciones:

1. **JWT de usuario**: mejor integración con sesión real, pero exige login nativo o transferencia segura desde web.
2. **Ingest key dedicada**: más simple para puente, pero debe protegerse como secreto.

Recomendación MVP:

- Usar `X-Ingest-Key` con una clave específica de ingesta nutricional.
- Guardar con Android Keystore / EncryptedSharedPreferences.
- No poner la clave en URL salvo compatibilidad manual; evitar `?key=` en la app porque puede acabar en logs/proxies.

### TLS

- Aceptar solo HTTPS.
- No permitir cleartext traffic.
- Validar hosts allowlist.
- Certificate pinning opcional, no recomendado al inicio por riesgo operativo con DuckDNS/Render y rotación de certificados.

### WebView

Si se usa fallback:

- Allowlist estricta de hosts.
- Safe Browsing ON.
- JavaScript solo si la web lo requiere.
- Sin `addJavascriptInterface`.
- Desactivar acceso a archivos.
- Bloquear mixed content.
- Abrir enlaces externos en navegador.

### Logs

- Redactar JWT, API key y payloads completos.
- Guardar solo `dedupe_hash`, timestamps, macros agregados y errores sanitizados.
- Modo diagnóstico exportable solo con acción explícita del usuario.

## 17. Pantallas mínimas MVP

### 1. Home

- Botón `Abrir Bolus AI`.
- Estado servidor: principal / backup / sin conexión.
- Último envío nutricional.
- Botón `Sincronizar ahora`.
- Aviso discreto si usa backup.
- Badge si hay cola pendiente.

### 2. Ajustes

- URL principal.
- URL backup.
- Clave/JWT de ingesta.
- Activar/desactivar nutrición automática.
- Modo de envío: manual / preguntar / automático.
- Probar conexión.
- Gestionar permisos Health Connect.
- Ver cola pendiente.
- Borrar logs y cola.

### 3. Diagnóstico

- Health Connect disponible/no disponible.
- Permisos concedidos.
- Último error.
- Última respuesta backend sanitizada.
- Últimos eventos de sync.
- Orígenes Health Connect detectados.
- Cantidad de NutritionRecords leídos en última ventana.

## 18. Plan por fases

### Fase 0: Estudio

- Revisar backend Bolus AI.
- Confirmar endpoint actual.
- Documentar el contrato JSON ya usado por el flujo iOS actual.
- Confirmar existencia de `/healthz` y `/api/health/check`.
- Definir el protocolo de validación Android para comparar `NutritionRecord` de MyFitnessPal contra los campos ya conocidos de Bolus AI.
- Confirmar decisión de portal: TWA como primera opción, Custom Tabs como fallback y WebView endurecido solo como último recurso.

Estado: este documento cubre el análisis inicial; falta captura real de datos Android para validar la equivalencia MyFitnessPal iOS → Health Connect Android, no para rediseñar el contrato del backend.

### Fase 1: APK puerta

- Crear app Kotlin/Compose.
- Icono propio.
- Home, Ajustes y Diagnóstico básicos.
- Config principal/backup.
- Health check.
- Failover visual.
- Abrir Bolus AI vía TWA.
- Fallback Custom Tabs y, solo si falla lo anterior, WebView endurecido.

### Fase 2: Lectura Health Connect manual y validación contra iOS

Objetivo de la fase: **verificar cómo Health Connect representa en Android los mismos datos que Bolus AI ya recibe correctamente desde iOS**, no descubrir de nuevo el formato final del backend.

- Integrar Health Connect Client.
- Pedir `READ_NUTRITION`.
- Botón `Buscar comidas nuevas`.
- Mostrar últimos `NutritionRecord` en modo diagnóstico.
- Guardar Health Connect Logs sanitizados de cada registro detectado y del JSON que se generaría, sin enviar todavía.
- Comparar los valores de Health Connect con una comida equivalente del flujo iOS actual.
- Verificar si los valores coinciden con los enviados actualmente desde iOS.
- Verificar si `metadata.dataOrigin.packageName` identifica el origen como MyFitnessPal.
- Verificar si `metadata.id` es estable entre lecturas y tras ediciones en MyFitnessPal.
- Verificar si Health Connect agrupa la información por comida o por nutriente.
- Verificar si `startTime`/`endTime` coinciden con la hora real de la comida o con la hora de edición/sincronización.
- Verificar si fibra, proteína, grasa y calorías aparecen con las mismas unidades esperadas por Bolus AI.
- Verificar si al editar una comida en MyFitnessPal se genera un update del mismo registro, un registro nuevo o duplicados.
- Mostrar origen/app fuente.
- No enviar todavía.

### Fase 3: Envío manual a Bolus AI

- Mapear `NutritionRecord` a payload Bolus AI usando el contrato ya validado por iOS.
- Configurar secreto/JWT.
- Enviar manualmente.
- Dedupe local.
- Cola Room persistente antes del POST para cumplir “Never lose a meal”.
- Registrar log sanitizado de JSON generado, endpoint utilizado y respuesta backend.
- Mostrar respuesta backend.

### Fase 4: Sincronización automática

- Toggle automático ON/OFF.
- Garantizar que OFF cancela workers, impide lecturas Health Connect e impide crear nuevos logs.
- WorkManager periódico.
- Permiso background si procede.
- Reintentos con backoff.
- Notificaciones de éxito/fallo.
- Modo preguntar antes de enviar.

### Fase 5: Integración avanzada

- Widget Android con glucosa actual, última comida, servidor activo y estado de sincronización.
- Tile Wear OS futuro para Pixel Watch: `Pixel Watch → Bolus AI Companion → Tile → información rápida`.
- Notificaciones inteligentes.
- Hermes/Bolus AI context bridge.
- Compatibilidad xDrip/Juggluco/Nightscout mediante `GlucoseProvider`.
- Providers futuros desacoplados: nutrición, glucosa, actividad, dispositivos y Hermes.
- Bluetooth nativo para básculas y dispositivos BLE, empezando por `ProzisBitScaleProvider`.
- Idempotency-Key backend.
- Endpoint `/api/mobile/health`.

## 19. Checklist antes de implementar

### Backend

- [ ] Confirmar que producción principal responde `GET https://bolus-ai.duckdns.org/healthz`.
- [ ] Confirmar que Render responde `GET https://bolus-ai-1.onrender.com/healthz`.
- [ ] Confirmar `NUTRITION_INGEST_SECRET` activo en ambos entornos.
- [ ] Confirmar CORS no afecta a cliente nativo Retrofit.
- [ ] Decidir si la app usará JWT o ingest key.
- [ ] Evaluar añadir `external_id`/`dedupe_hash` a notas o modelo.

### Android

- [ ] Crear package name definitivo.
- [ ] Crear icono y nombre visible.
- [ ] Preparar privacidad/disclosure de Health Connect.
- [ ] Probar Health Connect con MyFitnessPal real usando comidas de control comparables con iOS.
- [ ] Verificar packageName de MyFitnessPal en `DataOrigin`.
- [ ] Verificar estabilidad de `metadata.id` entre lecturas y tras editar comidas en MyFitnessPal.
- [ ] Verificar si Health Connect agrupa por comida o por nutriente.
- [ ] Verificar si `NutritionRecord` trae calorías, fibra, proteína, grasa y mealType con unidades equivalentes a las usadas por Bolus AI.
- [ ] Verificar si el horario corresponde a la comida real o a la sincronización/edición.
- [ ] Verificar si las ediciones en MyFitnessPal generan duplicados.
- [ ] Verificar si se necesita background read permission.
- [ ] Preparar Digital Asset Links para TWA.

### Seguridad y privacidad

- [ ] No guardar claves en texto plano.
- [ ] No enviar si toggle OFF.
- [ ] No registrar payloads sensibles completos.
- [ ] Borrar cola/logs desde ajustes.
- [ ] Política de privacidad actualizada.
- [ ] Retención local definida.

## 20. Fuentes técnicas consultadas

### Código y documentación del repositorio

- `backend/app/api/integrations.py`: normalización, autenticación, deduplicación e ingesta nutricional.
- `backend/app/main.py`: endpoints `/healthz` y `/api/health/check`.
- `docs/INTEGRATIONS_NUTRITION.md`: autenticación y ejemplos de ingesta.
- `docs/ARCHITECTURE_MAP.md`: inventario de entradas/salidas y rol de la ingesta nutricional.

### Documentación externa oficial/relevante

- Android Health Connect data types: `NutritionRecord`, `READ_NUTRITION`, permisos adicionales de background/history. https://developer.android.com/health-and-fitness/health-connect/data-types
- Android Health Connect read data: foreground/background reads, límites históricos, excepciones y reintentos. https://developer.android.com/health-and-fitness/health-connect/read-data
- Google Play Android Health Permissions guidance. https://support.google.com/googleplay/android-developer/answer/12991134
- Android Trusted Web Activities overview. https://developer.android.com/develop/ui/views/layout/webapps/trusted-web-activities
- Android security best practices for WebView and storage. https://developer.android.com/privacy-and-security/security-best-practices

## 21. Próximos pasos concretos

1. Validar en un Android real una exportación de MyFitnessPal a Health Connect y capturar 3-5 `NutritionRecord` representativos con comidas de control equivalentes al flujo iOS.
2. Confirmar si los valores, unidades y horarios coinciden con lo que Bolus AI ya recibe desde iOS.
3. Confirmar si `metadata.dataOrigin.packageName` identifica consistentemente a MyFitnessPal y si `metadata.id` permanece estable tras relecturas/ediciones.
4. Confirmar si Health Connect agrupa por comida o por nutriente y si las ediciones de MyFitnessPal generan duplicados.
5. Confirmar el nombre de paquete final y preparar `assetlinks.json` para TWA.
6. Decidir secreto de ingesta vs JWT para MVP.
7. Implementar Fase 1 como APK puerta sin tocar backend.
8. Implementar Fase 2 con lectura manual y pantalla de diagnóstico antes de habilitar envíos.
9. Ejecutar prueba extremo a extremo manual con backup/failover y cola local.

## 22. Conclusión

La solución recomendada es construir **Bolus AI Companion** como app Android nativa mínima con experiencia web mediante **TWA**, fallback **Custom Tabs** y WebView endurecido solo como última opción, más módulo nativo Health Connect. Esta arquitectura evita depender de Tasker, mejora mantenibilidad, permite failover, respeta permisos de salud y permite evolucionar hacia sincronización automática robusta. El backend actual ya es suficiente para un MVP sin cambios obligatorios, aunque una mejora futura de idempotencia explícita haría el sistema más sólido.
