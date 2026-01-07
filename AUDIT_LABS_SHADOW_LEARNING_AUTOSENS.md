# Auditoría técnica y de seguridad

> Alcance: **Ajustes → LABS → Shadow mode**, **Historial de aprendizaje**, y **AutoSens**.
> Objetivo: verificar funcionamiento real, valor, y seguridad clínica/UX. Incluir rutas, tablas, jobs, logs y tests.

---

## 0) Inventario rápido

### Referencias encontradas (UI / API / servicios / DB)

**Shadow / Labs / Learning (frontend)**
- `frontend/src/pages/LabsPage.jsx` → toggle de Shadow Mode (Labs).
- `frontend/src/pages/StatusPage.jsx` → tarjeta “Aprendizaje (Shadow Labs)” consume `/api/analysis/shadow/logs`.
- `frontend/src/pages/SettingsPage.jsx` → flags `labs.shadow_mode_enabled` y `learning.auto_apply_safe`.
- `frontend/src/lib/api.ts` → `getShadowLogs()`.

**Learning / Shadow (backend)**
- `backend/app/models/learning.py` → tablas `meal_entries`, `meal_outcomes`, `shadow_logs`.
- `backend/app/services/learning_service.py` → guarda comidas, evalúa outcomes (Nightscout), hints.
- `backend/app/api/analysis.py` → `/api/analysis/shadow/logs`.
- `backend/app/jobs.py` → job `learning_eval` cada 30 min.
- `backend/app/bot/proactive.py` → `post_meal_feedback()` guarda eventos en `events.json`.

**AutoSens (frontend)**
- `frontend/src/pages/StatusPage.jsx` → estado Autosens.
- `frontend/src/pages/SettingsPage.jsx` → toggle autosens + min/max ratio.
- `frontend/src/pages/BolusPage.jsx` → muestra explicación Autosens en cálculo.

**AutoSens (backend)**
- `backend/app/services/autosens_service.py` → cálculo Autosens (24h).
- `backend/app/services/dynamic_isf_service.py` → TDD ponderado (7d) y límites.
- `backend/app/api/autosens.py` → `/api/autosens/calculate`.
- `backend/app/api/bolus.py` → aplica autosens en cálculo de bolo + “advisor” crea sugerencias.
- `backend/app/api/forecast.py` → usa autosens para modificar ICR/ISF de proyección.
- `backend/app/models/settings.py` → `autosens.enabled` **default True**.

### Flujo completo (UI → API → servicio → DB → lectura)

**Shadow Mode (LABS)**
1. UI: `LabsPage.jsx` toggle → `updateSettings()`.
2. API: `/api/settings/` (no específico de labs) persiste `labs.shadow_mode_enabled`.
3. Servicio: **no hay** servicio/cron que escriba `shadow_logs` cuando se activa.
4. DB: `shadow_logs` existe pero no se llena por ninguna ruta conocida.
5. Lectura: `/api/analysis/shadow/logs` y UI en `StatusPage.jsx`.

**Historial de aprendizaje**
1. UI: `StatusPage.jsx` consume `/api/analysis/shadow/logs`.
2. API: `analysis.get_shadow_logs` ahora combina DB `shadow_logs` + eventos JSON (`events.json`) + **resultados de `meal_outcomes`**.
3. Servicio: `LearningService.save_meal_entry` al guardar tratamientos; `LearningService.evaluate_pending_outcomes` vía job `learning_eval`.
4. DB: `meal_entries` + `meal_outcomes`.
5. Lectura: `/api/analysis/shadow/logs` mostrado en “Aprendizaje (Shadow Labs)”.

**AutoSens**
1. UI: `StatusPage.jsx`, `SettingsPage.jsx`, `BolusPage.jsx`.
2. API: `/api/autosens/calculate`, `/api/bolus/calc`, `/api/forecast/simulate`.
3. Servicios: `AutosensService.calculate_autosens`, `DynamicISFService.calculate_dynamic_ratio`.
4. DB: usa `treatments` como datos, **no persiste resultados** de Autosens.
5. Lectura: UI lee ratio on-demand, sin historial.

---

## 1) Shadow Mode (LABS)

### 1.1 ¿Qué promete hacer?
- UI declara “analiza decisiones vs resultados reales para aprender”.
- Toggle en Labs actualiza `settings.labs.shadow_mode_enabled`.
- En notificaciones: se sugiere activar cuando “shadow labs ready” (requiere logs).

### 1.2 ¿Qué hace en realidad?
- **No hay escritura de `shadow_logs`** desde ningún endpoint o job.
- `/api/analysis/shadow/logs` solo lee `shadow_logs` + eventos JSON y, ahora, outcomes de aprendizaje.
- No existe job dedicado “shadow run”. No se guarda persistencia específica por shadow mode.
- Resultado: el toggle **no dispara procesamiento adicional**.

### 1.3 Por qué “nunca ha funcionado”
Causas concretas:
1. **No hay generación de `shadow_logs`** al activar Shadow Mode.
2. **El pipeline de feedback del bot no registra resultados** (`feedback_ok/low/high` no tiene handler), dejando `events.json` sin outcome.
3. Aunque `learning_eval` existe, sus resultados se guardan en `meal_outcomes`, pero la UI solo mostraba `shadow_logs` (ahora corregido para incluir outcomes).

### 1.4 Decisión
- **Estado real:** “Solo apariencia” (flag UI sin job/persistencia propia).
- **Recomendación A (segura y simple):** ocultar o desactivar el toggle hasta que exista un pipeline real. Mantener flag para rollback.
- **Recomendación B (mínimo útil):** crear una tabla `shadow_runs` y un job que simule y guarde resultados sin afectar cálculos. Exponer logs en UI.

---

## 2) Historial de aprendizaje (vacío)

### 2.1 ¿Qué es “aprendizaje” hoy?
- **Evento base:** al guardar un tratamiento (`/api/bolus/treatments`) se crea `MealEntry`.
- **Resultado:** `LearningService.evaluate_pending_outcomes` calcula `MealOutcome` con Nightscout a las ~4h.
- **Tabla clave:** `meal_entries`, `meal_outcomes`.

### 2.2 Auditoría de pipeline
- **Escritura:**
  - `LearningService.save_meal_entry` al guardar un tratamiento.
  - `LearningService.evaluate_pending_outcomes` (job `learning_eval`).
- **Persistencia:** en DB (`meal_entries`, `meal_outcomes`).
- **Lectura:** la UI consultaba `shadow_logs`, sin mapear outcomes → historial.
- **Filtros/limpieza:** no hay TTL explícito en learning; job evalúa solo entre 4h y 24h.

**Causa raíz del “vacío”:** la UI consultaba logs que nunca se llenan (`shadow_logs`) y el feedback del bot no se guarda como outcome.

### 2.3 Corrección mínima aplicada
- Se actualizó `/api/analysis/shadow/logs` para **incluir `MealOutcome`** y mostrar resultados reales.
- Se añadió test de integración para asegurar que los outcomes aparecen y están ordenados.

---

## 3) AutoSens: seguridad y sentido

### 3.1 Qué pretende AutoSens
- **Modifica ratios en cálculos:**
  - `Bolus` → aplica `autosens_ratio` en cálculo de bolo.
  - `Forecast` → ajusta ISF/ICR en simulación.
- **No aplica cambios automáticamente en settings**, salvo cuando el “advisor” crea sugerencias (aceptación manual).

### 3.2 Riesgos (P0/P1/P2)
- **P0:** Autosens está **enabled por defecto** (`autosens.enabled = True`), lo que implica modificaciones automáticas en cálculos sin explicitación clínica.
- **P1:** No hay persistencia de runs ni trazabilidad (“por qué cambió”), ni auditoría histórica en DB.
- **P1:** “Advisor” puede generar sugerencias sin mostrar el dataset completo ni criterios de exclusión.
- **P2:** Ventana corta (24h) puede producir volatilidad, aunque hay clamps locales (0.9–1.1 + global 0.6–1.4).

### 3.3 Auditoría de implementación
- **Dónde corre:** `/api/bolus/calc`, `/api/autosens/calculate`, `/api/forecast/simulate`.
- **Scheduler:** no hay job periódico; se calcula on-demand.
- **Persistencia:** **no se guarda** `autosens_runs` ni input/output.
- **Guardrails:** clamps en `AutosensService` y límites por `DynamicISFService`; no guarda decisiones ni validaciones de calidad de datos.

### 3.4 Decisión de producto
- **Si no se valida clínicamente:** AutoSens debería quedar **OFF por defecto** y bajo Labs.
- **Si se mantiene:** añadir `autosens_runs` con input summary, límites estrictos, y tests de guardrails (hipos recientes, pocos datos, clamp por día).

---

## 4) Evidencias técnicas (paths, tablas, jobs, logs, tests)

### Rutas API relevantes
- `/api/analysis/shadow/logs` → historial de aprendizaje/shadow.
- `/api/autosens/calculate` → ratio autosens actual.
- `/api/bolus/calc` → aplica autosens en cálculo.
- `/api/forecast/simulate` → autosens en proyección.

### Tablas
- `meal_entries`, `meal_outcomes`, `shadow_logs`.
- `treatments` (input de autosens y learning).
- `suggestions` (Autosens advisor crea `ParameterSuggestion`).

### Jobs / cron
- `learning_eval` (cada 30 min) → calcula outcomes.

### Logs / eventos
- `events.json` (DataStore) → `post_meal_feedback` sólo registra “asked”, no outcome.

### Tests añadidos
- `tests/test_learning_history.py` verifica que `meal_outcomes` aparece en `/api/analysis/shadow/logs` y ordena por fecha.

---

## 5) Recomendación final

**Shadow Mode**
- **Estado real:** No operativo.
- **Acción recomendada:** esconder/desactivar el toggle, o construir pipeline mínimo con `shadow_runs` + UI.

**Historial de aprendizaje**
- **Estado real:** parcialmente roto (UI leía logs vacíos). **Corregido** al incluir outcomes.
- **Acción recomendada:** mantener job `learning_eval` y monitorear ejecución; añadir endpoint dedicado si se quiere más detalle.

**AutoSens**
- **Estado real:** funcional pero sin auditoría persistente ni seguridad clínica formal.
- **Acción recomendada:** OFF por defecto + feature flag + tabla de auditoría.

