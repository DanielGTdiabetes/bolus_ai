# Dirección Hermes editable — Companion alpha11

17/10/2026: instalada `org.bolusai.companion` 0.2.0-alpha11/code14 en el Pixel
mediante `adb install -r`, mismo firmante, datos y 12 preferencias conservadas.

En Más → Ajustes del móvil aparece **Servidor Hermes (MyFitnessPal)** y el botón
**Guardar servidor Hermes**. Se guarda una URL base HTTP(S), sin credenciales,
query, fragmento ni sufijo `/mfp/sync-now`. El cliente añade ese sufijo. Guardar
no inicia una sincronización. Se usa el setter existente, sin cambiar el valor
por defecto ni trasladar cálculos clínicos al móvil.

El valor actual sigue siendo `http://100.65.212.74:8776` (BMAX). Solo cambiarlo a
`http://100.93.23.103:8776` cuando el trigger MFP esté validado en EVO durante C.2.
La URL principal NAS y el backup Render se conservaron. Faceclaw8791 es otro ajuste.

Verificación: 64 tests unitarios correctos y assembleDebug correcto. Lint mantiene
5 errores anteriores a este cambio: NewApi, ProtectedPermissions,
PermissionImpliesUnsupportedChromeOsHardware y dos JavascriptInterface.
Comparación con copia intacta: ninguna incidencia nueva de código; avisos de
GradleDependency difieren por metadatos online/offline, sin actualizar dependencias.
Campo y botón comprobados en UI. No se pulsó sincronización ni se cambió la URL.

APK: `artifacts/bolus-ai-companion-0.2.0-alpha11-hermes-url-debug.apk`, SHA256
`a7b444dcfc7139991a30241b07d22c5d36c471e69a9c322172334bebf0aa6789`.
Reversión alpha10 guardada en el workspace de migración, fuera de Git. Conservar
firma/datos; no desinstalar ni borrar datos para volver. No se han publicado cambios.

Migración: el primer intento C.1 de Hermes se revirtió por pérdida USB del Pixel
antes de cambiar Faceclaw. Producción y MFP siguen en BMAX. NAS ya admite ambas
IP de Agent API, con misma imagen/datos. Render no requirió cambios identificados.
