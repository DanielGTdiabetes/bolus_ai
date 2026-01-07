# Audit: Filtro anti-compresión (falsos bajos nocturnos)

## Estado real
**Estado actual:** **Activo pero condicionado**. El detector existe y ahora se aplica en los endpoints críticos de glucosa y en los servicios de análisis (ISF/autosens) **cuando** `nightscout.filter_compression` está habilitado. Sin embargo, el valor por defecto en configuración es `false` y `config/config.json` no define estos parámetros, por lo que **en producción típicamente queda inactivo** salvo configuración explícita.

**Conclusión:** no es código muerto, pero estaba parcialmente aplicado en el camino crítico (solo GET /api/nightscout/current y /api/nightscout/entries). Se integró el filtro en el endpoint POST (usado por frontend) y en los servicios de análisis (ISF/autosens). Además, el cálculo de bolos ahora emite warnings si detecta compresión en la lectura usada.

## Evidencia rápida (paths clave)
- Detector/heurística: `backend/app/services/smart_filter.py`.
- Endpoints SGV: `backend/app/api/nightscout.py` (`/current` y `/entries`).
- UI bandera: `frontend/src/pages/HomePage.jsx`.
- Servicios de análisis: `backend/app/services/isf_analysis_service.py`, `backend/app/services/autosens_service.py`.
- Cálculo de bolo: `backend/app/api/bolus.py` (warning por compresión detectada en lectura actual).
- Config global: `backend/app/core/settings.py`.

## 1) INVENTARIO (referencias encontradas)
1. **frontend/src/pages/HomePage.jsx**
   - Muestra banner de “Posible falsa bajada (Compresión)” si `is_compression` viene en `/api/nightscout/current`.
   - Subraya el valor de glucosa cuando hay compresión.
   - Se usa para la tarjeta “Glucosa Actual”.
   - Depende del backend para el flag.
   - No calcula compresión localmente.

2. **backend/tests/test_smart_filter.py**
   - Tests de `CompressionDetector`.
   - Verifica patrón drop→low→rebound.
   - Verifica exclusión con tratamiento reciente.
   - Verifica desactivación diurna.
   - Incluye nuevos casos sintéticos exigidos por el pedido.

3. **backend/app/api/nightscout.py**
   - `/current` GET y POST ahora aplican el detector (si está habilitado).
   - `/entries` retorna historial con flags `is_compression`.
   - Usa tratamientos recientes para excluir hipos reales.
   - Marca solo, no elimina lecturas.
   - Devuelve `compression_reason` para UI.

4. **backend/app/api/forecast.py**
   - Comentario sobre “compression recovery” en forecast.
   - Autosens usado en forecast ahora recibe filtro (indirecto).
   - No marca SGV directamente.
   - Impacto indirecto vía autosens.
   - Sin flags en respuesta.

5. **backend/app/services/smart_filter.py**
   - Implementa `CompressionDetector`.
   - Marca `is_compression` + `compression_reason`.
   - Ventana nocturna configurable.
   - Excluye si hay tratamiento reciente.
   - Solo flagging, no borrado.

6. **backend/app/core/settings.py**
   - Config global `nightscout.filter_compression` (default `false`).
   - Umbrales de caída/rebote y ventana nocturna.
   - No está habilitado por defecto.
   - Se usa en endpoints y análisis.
   - Controla activación real.

7. **backend/app/static/assets/bridge-Dai_Y0Fd.js**
   - Bundle compilado que también muestra el banner de compresión.
   - Artefacto generado (no fuente).
   - Refleja el mismo UI que HomePage.jsx.
   - No contiene lógica del filtro.
   - Solo resultado de build.

## 2) CAMINO CRÍTICO
| Endpoint | ¿aplica filtro? | ¿cómo? | ¿qué devuelve? |
|---|---|---|---|
| **/api/nightscout/current (GET)** | Sí (si `filter_compression=true`) | Lee SGV de la última hora + tratamientos (2h), ejecuta `CompressionDetector` y marca el último punto | `is_compression`, `compression_reason` en la respuesta |
| **/api/nightscout/current (POST)** | Sí (si `filter_compression=true`) | Igual que GET pero con config stateless (URL/token del cliente) | `is_compression`, `compression_reason` |
| **/api/nightscout/entries** | Sí (si `filter_compression=true`) | Ejecuta detector sobre historial y devuelve array enriquecido | Array de SGV con `is_compression` por lectura |
| **/api/bolus/calc** | Parcial | Si toma CGM, detecta compresión (si habilitado) y añade warning; no elimina la lectura | Respuesta de bolo con `warnings` sobre compresión |
| **/api/isf/analysis** | Sí (si `filter_compression=true`) | Filtra lecturas marcadas antes de calcular ISF observado | Respuesta ISF sin flags (filtrado interno) |
| **Autosens** | Sí (si `filter_compression=true`) | Descarta pares de SGV marcados como compresión en la ventana | Ratio autosens con datos limpios |

## 3) SEMÁNTICA DE SEGURIDAD
- **Flagging, no borrado:** el detector solo añade `is_compression` y `compression_reason` a lecturas; el historial se devuelve completo.
- **Exclusiones por tratamiento:** si hay carbs/insulina dentro de `treatments_lookback_minutes` (default 120 min), **no marca** compresión.
- **Ventana nocturna:** por defecto 23:00–07:00; configurable con `filter_night_start`/`filter_night_end`.
- **Umbrales:** caída ≥15 mg/dL en ~5 min, rebote ≥15 mg/dL en ~15 min (con tolerancias en el código).
- **Conservador:** si no se cumplen drop+rebound+no tratamientos, no marca.

## 4) PRUEBA REPRODUCIBLE
Se añadieron tests pytest con series sintéticas:
- **Compresión:** caída rápida → low breve → rebote rápido => `is_compression=True`.
- **Hipo real con tratamiento cercano:** no debe marcar.

Comando: `pytest backend/tests/test_smart_filter.py`

## 5) INTEGRACIÓN
- El filtro estaba **parcialmente aplicado** (GET /current y /entries), pero el frontend usa POST /current con config local, lo que lo hacía **inactivo en la UI**.
- Se integró el detector en **POST /current** y en los análisis **ISF** y **autosens**.
- En **/api/bolus/calc**, si se usa CGM, se añade un **warning** de compresión (sin descartar la lectura).

## 6) DECISIÓN
**Mantener e integrar** (no eliminar). El filtro es útil, conservador y ahora cubre el camino crítico completo cuando se habilita en configuración.
