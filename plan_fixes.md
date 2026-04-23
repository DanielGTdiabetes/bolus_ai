# Plan de Correcciones — Bolus AI

> Plan de implementación ajustado según preferencias del usuario:
> 1. Prioridad: bugs críticos primero
> 2. CatBoost: dependencia obligatoria
> 3. Thresholds: relajados
> 4. Persistencia de snapshots: la opción más óptima y eficaz

---

## Fase 1: Bugs Críticos (PRIORIDAD MÁXIMA)

### 1.1 SNAPSHOT_STORAGE persistente en disco (JSON con TTL)

**Problema**: `SNAPSHOT_STORAGE` es un dict en memoria. Si el proceso reinicia, se pierden todas las confirmaciones de bolo pendientes.

**Solución**: Reemplazar el dict por un `JSONStore` con TTL automático:
- Ruta: `{data_dir}/bot_snapshots.json`
- Cada snapshot se guarda con `expires_at = now + 30 min`
- Al cargar, se purgan los expirados
- El dict en memoria se mantiene como caché, pero el JSON es la fuente de verdad

**Archivos a tocar**:
- `backend/app/bot/service.py` (líneas 43, 1483, 2620)

**Implementación**:
```python
# Nuevo archivo: backend/app/bot/snapshot_store.py
class SnapshotStore:
    TTL_SECONDS = 1800  # 30 minutos
    
    def __init__(self, data_dir: Path):
        self.path = data_dir / "bot_snapshots.json"
        self._cache: dict = {}
        self._load()
    
    def _load(self):
        if self.path.exists():
            with open(self.path, "r") as f:
                data = json.load(f)
            now = datetime.now(timezone.utc).timestamp()
            self._cache = {
                k: v for k, v in data.items()
                if v.get("expires_at", 0) > now
            }
            self._persist()
    
    def _persist(self):
        with open(self.path, "w") as f:
            json.dump(self._cache, f, default=str)
    
    def get(self, key: str) -> Optional[dict]:
        return self._cache.get(key)
    
    def set(self, key: str, value: dict):
        value["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=self.TTL_SECONDS)).timestamp()
        self._cache[key] = value
        self._persist()
    
    def delete(self, key: str):
        self._cache.pop(key, None)
        self._persist()
```

### 1.2 IOB=0 fallback peligroso → rechazar cálculo

**Problema**: Cuando IOB es unavailable/stale, después de confirmación del usuario se asume `iob_for_calc = 0.0`. Esto puede causar sobredosis si hay insulina activa real.

**Solución**:
- En `bolus_calc_service.py:484`: cambiar fallback de `0.0` a `None`
- En `bolus_engine.py`: si `iob_u is None`, lanzar excepción con mensaje claro → el endpoint devuelve HTTP 424 con `error_code = "IOB_UNCERTAIN"`
- El usuario debe introducir manualmente su IOB estimado o esperar a que el sistema lo recupere

**Archivos a tocar**:
- `backend/app/services/bolus_calc_service.py`
- `backend/app/services/bolus_engine.py`

### 1.3 Eliminar ~1000 líneas de código duplicado

**Problema**: En `proactive.py` hay 4 funciones duplicadas completas:
- `basal_reminder()` (líneas 70-411 y 413-624)
- `premeal_nudge()` (líneas 629-759 y 761-897)
- `combo_followup()` (líneas 898-1079 y 1081-1273)
- `trend_alert()` (líneas 1542-1762 y 1764-1949)

**Solución**: Eliminar la segunda copia de cada función (las líneas más altas son las duplicadas inalcanzables).

**Archivo a tocar**:
- `backend/app/bot/proactive.py`

### 1.4 Double autosens clamping

**Problema**: El ratio autosens se clampa dos veces con bounds potencialmente diferentes:
- `bolus_calc_service.py:398-400` (usa `user_settings.autosens.min_ratio/max_ratio`)
- `bolus_engine.py:151-152` (hardcoded [0.7, 1.3])

**Solución**: Eliminar el clamp en `bolus_engine.py`. El engine debe confiar en el ratio que recibe ya ajustado.

**Archivos a tocar**:
- `backend/app/services/bolus_engine.py`

### 1.5 DIA hardcoded en recalc_second

**Problema**: `bolus_split.py:162` usa DIA=4.0, curve="walsh", peak=75 hardcoded.

**Solución**: Pasar `user_settings` al servicio y usar:
- `user_settings.iob.dia_hours`
- `user_settings.iob.curve`
- `user_settings.iob.peak_minutes`

**Archivo a tocar**:
- `backend/app/services/bolus_split.py`

### 1.6 Duration hardcoded 240min en dual bolus

**Problema**: Todos los dual boluses obtienen `duration_min=240` sin importar si son por Warsaw o por fibra.

**Solución**:
- Warsaw (fat/protein) → 240 min (correcto)
- Fibra auto-split → 120 min (la fibra se absorbe más rápido)
- Añadir campo `duration_min` al `CalculationResult`

**Archivo a tocar**:
- `backend/app/services/bolus_engine.py`

---

## Fase 2: ML CatBoost (Funcional por defecto)

### 2.1 Añadir catboost a requirements.txt

```
catboost>=1.2,<2.0
pandas>=2.0
numpy>=1.24
```

### 2.2 Llamar `load_models()` en startup

En `main.py`, después de `MLInferenceService.get_instance()`, añadir:
```python
svc = MLInferenceService.get_instance()
svc.load_models()  # Intentar cargar modelos existentes
```

### 2.3 Entrenar p10 y p90 además de p50

En `ml_trainer_service.py`, en el loop de training:
```python
# p50 (ya existe)
model_p50 = CatBoostRegressor(..., loss_function='RMSE')
model_p50.fit(X, y)

# p10
model_p10 = CatBoostRegressor(..., loss_function='Quantile:alpha=0.1')
model_p10.fit(X, y)

# p90
model_p90 = CatBoostRegressor(..., loss_function='Quantile:alpha=0.9')
model_p90.fit(X, y)
```

**Nota**: 3x tiempo de entrenamiento. Como corre a las 03:00, es aceptable.

### 2.4 Relajar gate de calidad para primer modelo

En `ml_trainer_service.py:256`:
```python
# Si no hay modelo previo, relajar gate
is_first_model = current_meta is None
threshold = 60.0 if is_first_model else ml_cfg.model_quality_max_rmse
if avg_mae > threshold:
    return {"status": "rejected", ...}
```

### 2.5 Endpoint de estado ML

Nuevo endpoint `GET /api/ml/status`:
```json
{
  "models_loaded": true,
  "snapshot_count": 1523,
  "training_enabled": true,
  "last_training_status": "success",
  "model_version": "v1-202401150300",
  "confidence_score": 0.8,
  "has_quantile_bands": true
}
```

---

## Fase 3: Sugerencias ISF/Autosens (Relajar thresholds)

### 3.1 Relajar Autosens Advisor

En `api/bolus.py:310-323`:
```python
# Antes:
if 0.99 <= ratio <= 1.01: return
if abs(current_isf - new_isf) < 1.0: return

# Después:
if 0.95 <= ratio <= 1.05: return  # 5% en lugar de 1%
if abs(current_isf - new_isf) < 0.5: return  # 0.5 en lugar de 1.0
```

### 3.2 Notificar sugerencias sin depender del bot

En `api/bolus.py:353-364`:
```python
# Guardar siempre en DB (ya lo hace)
# Intentar bot, pero no fallar silenciosamente si no hay bot
chat_id = config.get_allowed_telegram_user_id()
if chat_id and _bot_app:  # <-- añadir check de _bot_app
    await send_autosens_alert(...)
else:
    logger.info("Autosens suggestion created but bot not available for notification")
```

**Frontend**: Añadir badge en HomePage cuando hay sugerencias pending.

### 3.3 Relajar ISF Check job

En `suggestion_engine.py`:
```python
# Antes:
if total_valid < 5: continue
if bad_ratio > 0.30: continue
if short_ratio >= 0.60: ...
elif over_ratio >= 0.60: ...

# Después:
if total_valid < 3: continue  # 3 en lugar de 5
if bad_ratio > 0.50: continue  # 50% en lugar de 30%
if short_ratio >= 0.50: ...  # 50% en lugar de 60%
elif over_ratio >= 0.50: ...
```

### 3.4 Añadir sugerencias de ICR al ISF Check

Actualmente `generate_suggestions_service` ya genera sugerencias de ICR, pero el job `check_isf_suggestions` solo notifica las de ISF (`parameter == "isf"`). Cambiar para notificar TODAS las pending.

En `bot/proactive.py:1988`:
```python
# Antes:
ParameterSuggestion.parameter == "isf"

# Después:
# Notificar todas las pending, no solo ISF
# (eliminar el filtro de parameter)
```

### 3.5 Endpoint manual de generación

Nuevo endpoint `POST /api/suggestions/generate` que llama a `generate_suggestions_service(user_id, 14, session)` y devuelve las sugerencias creadas.

---

## Fase 5: Funcionalidades cuestionables — Restaurante y Microbolo

> **ESTADO**: ✅ COMPLETADO (2026-04-23)
> **Decisión**: MANTENER funcionalidad completa de "Modo Restaurante"

### 5.1 Modo Restaurante (Carta) — MANTENER + FIXES

**Decisión**: La funcionalidad SÍ tiene valor clínico real. Se mantiene el flujo completo:
1. Foto de carta/menú → Gemini estima HC totales
2. Bolo inicial del usuario
3. Escaneo secuencial de cada plato
4. Ajuste final basado en delta esperado vs real

**Problema clínico que intenta resolver**: En restaurante las raciones son 2-3x las caseras y hay grasas ocultas. La literatura muestra errores de ±30-50g en estimación de HC en restaurante.

**Fixes aplicados**:

| # | Fix | Estado | Archivo |
|---|-----|--------|---------|
| 1 | **ISF del usuario** (no hardcoded 15) | ✅ | `restaurant.py:437`, `api/restaurant.py:_get_user_isf()` |
| 2 | **Endpoints completos** | ✅ | `api/restaurant.py`: analyze_menu, analyze_menu_text, compare_plate |
| 3 | **Bolo dual automático** si grasa/proteína altas | ✅ | `RestaurantSession.jsx` sugiere dual |
| 4 | **Check de IOB** antes de sugerir insulina | ✅ | `RestaurantSession.jsx:317-336` |
| 5 | **Persistencia híbrida** (localStorage + BD) | ✅ | Non-blocking si falla BD |
| 6 | **Confirmaciones de seguridad** | ✅ | window.confirm solo para decisiones críticas |

**Archivos modificados**:
- `backend/app/api/restaurant.py` — 180 líneas, 4 endpoints
- `backend/app/services/restaurant.py` — guardrails con ISF dinámico
- `backend/app/models/restaurant_session.py` — modelo V2
- `frontend/src/lib/restaurantApi.js` — cliente actualizado
- `frontend/src/components/restaurant/RestaurantSession.jsx` — UX mejorada

**Documentación**: `docs/restaurant_fixes.md`

### 5.2 Microbolo Proactivo — SIMPLIFICAR + FIX DE SEGURIDAD URGENTE

**Problema clínico que intenta resolver**: Subidas lentas de glucosa que no justifican corrección completa pero que, sin acción, terminan en hiperglucemia prolongada. El concepto de "gentle correction" existe en sistemas AID reales (MiniMed 780G, Control-IQ).

**Qué hace actualmente**:
- Detecta BG > 140 + tendencia ascendente sin bolo/comida reciente
- Calcula: `needed = (BG - target) / CF`, luego `safeguarded = needed * 0.4`
- Redondea a step 0.5U, mínimo 0.5U, máximo 1.0U
- Envía alerta Telegram: "Un micro-bolo de X U podría aplanar la curva"

**Problemas identificados**:

| # | Problema | Gravedad |
|---|----------|----------|
| 1 | **NO comprueba IOB** — si hay insulina activa, el microbolo se suma y puede causar hipo | **CRÍTICA** |
| 2 | **Código duplicado** en dos sitios de `proactive.py` (~líneas 1727 y 1917) | Alta |
| 3 | **CF hardcoded a 30** como fallback — usa `cf.lunch` a las 22:00 | Media |
| 4 | **Step hardcoded a 0.5U** — muchos usuarios usan 0.05 o 0.1U | Media |
| 5 | **Máximo 1.0U fijo** — no es relativo al TDD del usuario | Media |
| 6 | **No distingue causa de subida** — estrés, fallo infusión, comida no declarada | Media |
| 7 | **Término confuso** — "microbolo" en literatura son 0.05-0.1U, aquí 0.5-1.0U | Baja |

**Cambios propuestos**:

- **MANTENER**: Idea de corrección parcial (30-40%) ante subidas lentas
- **CORREGIR URGENTE**:
  - Añadir check de IOB antes de sugerir cualquier microbolo
  - Si IOB > 0, reducir proporcionalmente o no sugerir
  - Unificar lógica duplicada en una sola función `calculate_microbolus_suggestion()`
- **CORREGIR**:
  - Usar step real del usuario (0.05/0.1/0.5), no hardcodear 0.5
  - Usar ISF/CF del momento del día actual, no siempre lunch
  - Hacer máximo configurable y relativo al TDD (ej: max 10% del TDD)
- **RENOMBRAR**: De "microbolo" a "mini-corrección" en toda la UI y mensajes

**Archivos a tocar**:
- `backend/app/bot/proactive.py` (eliminar duplicado, añadir IOB check)
- `backend/app/bot/llm/router.py` (renombrar mensajes)
- `backend/app/services/isf_analysis_service.py` (actualizar comentarios)
- `backend/app/services/learning_service.py` (actualizar comentarios)

---

## Fase 4: Frontend (UX)

### 4.1 Badge de sugerencias en HomePage

En `HomePage.jsx`, en el header o quick actions:
```jsx
{suggestionsCount > 0 && (
  <span className="badge-red">{suggestionsCount} sugerencias</span>
)}
```

Polling cada 5 min a `GET /api/suggestions?status=pending`.

### 4.2 Estado ML visible en StatusPage

Añadir sección "Machine Learning" que muestre:
- Estado (recolectando / entrenando / activo)
- Número de snapshots
- Versión del modelo activo
- Confianza

---

## Orden de ejecución propuesto

| Orden | Tarea | Archivos | Dificultad | Estado |
|-------|-------|----------|------------|--------|
| 1 | Eliminar código duplicado proactive.py | 1 | Baja | ✅ |
| 2 | Fix double autosens clamping | 1 | Baja | ✅ |
| 3 | Fix DIA hardcoded en recalc_second | 1 | Media | ✅ |
| 4 | Fix duration hardcoded 240min | 1 | Media | ✅ |
| 5 | **Microbolo: IOB check + eliminar duplicado** | 1 | **Alta (seguridad)** | ✅ |
| 6 | SNAPSHOT_STORAGE persistente | 2 | Media | ✅ |
| 7 | IOB=0 fallback → rechazar | 2 | Media | ✅ |
| 8 | Añadir catboost a requirements | 1 | Baja | ✅ |
| 9 | load_models() en startup + p10/p90 | 3 | Media | ✅ |
| 10 | Relajar gates ML | 1 | Baja | ✅ |
| 11 | Endpoint ML status | 2 | Baja | ✅ |
| 12 | Relajar thresholds autosens/ISF | 3 | Baja | ✅ |
| 13 | Notificar sin bot + frontend badge | 4 | Media | ✅ |
| 14 | Endpoint manual suggestions | 2 | Baja | ✅ |
| 15 | StatusPage ML info | 1 | Baja | ✅ |
| 16 | **Restaurante: MANTENER + fixes (ISF, endpoints, bolo dual, IOB check)** | 6 | Media | ✅ |
| 17 | ~~Restaurante: simplificar (eliminar carta, sesiones, scoring)~~ | 6 | Media | ❌ DESCARTADO |

---

## Checklist de finalización

- [x] Fase 1 completa (6 bugs críticos) — ✅ 100%
- [x] Fase 2 completa (ML CatBoost funcional) — ✅ 100%
- [x] Fase 3 completa (Sugerencias ISF/Autosens relajadas) — ✅ 100%
- [x] Fase 4 completa (Frontend UX) — ✅ 100%
- [x] Fase 5 completa (Restaurante mantenido + Microbolo seguro) — ✅ 100%
- [x] Tests pasan
- [x] Documentación actualizada (CLAUDE.md, docs/restaurant_fixes.md)

---

## Resumen Final (2026-04-23)

| Fase | Implementados | Pendientes | Total |
|------|--------------|------------|-------|
| Fase 1 (Bugs Críticos) | 6/6 | 0 | ✅ 100% |
| Fase 2 (ML CatBoost) | 5/5 | 0 | ✅ 100% |
| Fase 3 (Sugerencias) | 5/5 | 0 | ✅ 100% |
| Fase 4 (Frontend) | 2/2 | 0 | ✅ 100% |
| Fase 5 (Restaurante/Microbolo) | 4/4 | 0 | ✅ 100% |
| **TOTAL** | **22/22** | **0** | **✅ 100%** |

**Todos los fixes del plan_fixes.md han sido aplicados exitosamente.**
