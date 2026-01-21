# ML Training Data Pipeline (v2)

## Objetivo
Generar una fila cada 5 minutos en `ml_training_data_v2` con el estado actual del usuario (BG, eventos, parámetros activos, baseline forecast y flags de calidad) para entrenamiento de modelos futuros.

## Job
**Nombre:** `ml_training_snapshot`  
**Frecuencia:** cada 5 minutos  
**Dependencias:** solo backend (no requiere bot).

### Qué captura
- BG actual + tendencia + edad del dato.
- Eventos reconciliados (DB + Nightscout, sin duplicados).
- IOB/COB actuales.
- Ventanas de basal (24/48h) y basal activa.
- Ejercicio (treatments y modos temporales).
- Baseline forecast por horizonte (30/60/120/240/360).
- Flags de calidad y consistencia de fuentes.

## Tabla `ml_training_data_v2`
Campos clave:
- `feature_time`, `user_id`
- `bg_mgdl`, `trend`, `bg_age_min`
- `iob_u`, `cob_g`, `iob_status`, `cob_status`
- `basal_active_u`, `basal_total_24h`, `basal_total_48h`
- `baseline_bg_30m`, `baseline_bg_60m`, `baseline_bg_120m`, `baseline_bg_240m`, `baseline_bg_360m`
- `active_params` (JSON serializado con parámetros activos)
- `event_counts` (JSON serializado con conteos)
- `source_*` y `flag_*` (consistencia/ calidad)

## Notas de operación
- El job no dispara avisos ni notificaciones.
- Se ejecuta incluso cuando el bot está desactivado.
- El insert usa `ON CONFLICT` para evitar duplicados en el mismo `feature_time`.
