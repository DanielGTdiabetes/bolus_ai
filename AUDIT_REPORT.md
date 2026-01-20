# Auditoría Profunda - Post Cambios (Auto Export + Bot NAS/Render)

## Estado General
**OK (con mitigaciones aplicadas)**: El pipeline de ingestión es idempotente y conserva timestamps, con dedupe por firma estable y ventanas temporales. Se añadieron logs de trazabilidad y una estrategia de *leader election* con lock en DB para evitar conflictos webhook/polling entre NAS y Render.

## Hallazgos por Área

### Ingest Auto Export
- **Hallazgo:** El endpoint soporta payloads wrapper y directos, y agrupa métricas por timestamp para construir comidas.
- **Acción:** Se añadieron logs de trazabilidad (wrapper/direct, timestamps parseados, conteos de dedupe) y fixtures reales para validación.
- **Severidad:** P2 (observabilidad).

### Dedupe / Idempotencia
- **Hallazgo:** La firma en `notes` (`Imported from Health: <timestamp> #imported`) mantiene idempotencia incluso si el timestamp no parsea y se usa `now`.
- **Acción:** Tests de regresión que validan idempotencia, unicidad de IDs en respuesta, y no duplicación en enriquecimiento/edición.
- **Severidad:** P1 mitigado.

### Timestamps
- **Hallazgo:** Parseo multi-formato con fallback a `fromisoformat` y `now` si falla. El DB guarda UTC naïve.
- **Acción:** Test de preservación de timestamp con fixture real.
- **Severidad:** P1 mitigado.

### DB Treatments
- **Hallazgo:** Se actualiza tratamiento existente si hay enriquecimiento o edición en mismo timestamp. Conteos de `ingested_count` solo incluyen creaciones nuevas.
- **Acción:** Tests de enriquecimiento y edición estable.
- **Severidad:** P1 mitigado.

### Notificaciones
- **Hallazgo:** Notificación solo para ingestas válidas y con chat_id configurado.
- **Acción:** Sin cambios funcionales, solo observabilidad.
- **Severidad:** P2.

### Bot (Webhook/Polling)
- **Hallazgo:** Existía riesgo de “split brain” (NAS en polling vs Render en webhook), causando conflictos `getUpdates`.
- **Acción:** Se implementó *leader election* por lock en DB con TTL y heartbeat. Solo el líder recibe updates; el no-líder queda en modo send-only.
- **Severidad:** P0 mitigado.

### Emergency Mode
- **Hallazgo:** Render se mantiene en modo “send-only” fuera de emergencia.
- **Acción:** Ahora se unifica el modo “send-only” también para no-líderes.
- **Severidad:** P1 mitigado.

### Scheduler
- **Hallazgo:** Sin cambios. No se detectaron regresiones.
- **Severidad:** P2.

## Riesgos y Severidad
- **P0:** Conflicto webhook/polling (mitigado con leader lock en DB).
- **P1:** Dedupe y timestamps con payload agregado (mitigado con tests + logs).
- **P2:** Observabilidad y diagnóstico (mejorado con logs y reporte).

## Decisiones
- Mantener idempotencia estricta con firma en `notes` y ventanas temporales.
- Implementar *leader election* con TTL interno para evitar dependencias externas.
- No introducir nuevas dependencias.

## Tests de Regresión (Resumen)
Incluye tests con fixtures reales y casos de idempotencia, enriquecimiento, edición estable, y leader lock en DB.
