# AUDIT_REPORT_V2.md

## Resumen ejecutivo
- Se revisó backend (FastAPI), frontend (React/Vite) y bot Telegram con foco en rutas/funciones “zombie”, el flujo de sugerencias y el bug del botón “Analizar” en basal.
- Causa raíz del bug “Analizar”: el endpoint `/api/basal/night-scan` ejecutaba el análisis en modo *dry-run* (no persistía), por lo que el historial volvía a mostrar la acción pendiente y el botón nunca cambiaba de estado.
- Se aplicó fix en backend (persistir resultados) y en UI (estado de “Analizando” + bloqueo de doble click), y se añadieron logs mínimos para validar persistencia.

---

## Mapa de módulos y features reales

### Frontend (React/Vite)
- **Pages** (lazy load via `bridge.jsx`): Home, Bolus, Scan, Basal, Patterns, History, Suggestions, Settings, Forecast, Status, Notifications, Profile, etc.
- **Basal**: `BasalPage` (registro basal, check-ins, análisis nocturno y timeline de 14 días).
- **Sugerencias**: `SuggestionsPage` con tabs Pendientes/Aceptadas, aceptación de cambios y evaluación posterior.
- **Infra**: router hash + `mountReactPage`, bottom nav, estado local con `modules/core/store`.

### Backend (FastAPI)
- **Basal**: `/api/basal/*` (dosis, checkin, night scan, timeline, advice, evaluate-change).
- **Sugerencias**: `/api/suggestions/*` (generar, listar, aceptar, rechazar, evaluar, borrar).
- **Nightscout**: `NightscoutClient` + servicios de análisis nocturno.
- **Servicios**: `basal_engine`, `suggestion_engine`, `evaluation_engine`.
- **Persistencia**: modelos `BasalEntry`, `BasalCheckin`, `BasalNightSummary`, `ParameterSuggestion`, `SuggestionEvaluation`.

### Bot Telegram
- **Basal reminder**: flujo proactivo (recordatorio basal diario, registro y confirmaciones).
- **Sugerencias**: notificaciones y herramientas LLM para sugerencias/ajustes.

---

## Riesgos priorizados (P0/P1/P2)

### P0
1) **Análisis nocturno sin persistencia**: El endpoint `/api/basal/night-scan` ejecutaba el análisis pero no persistía resultados → UI siempre mostraba el botón “Analizar”. (Causa raíz del bug reportado.)

### P1
1) **Funciones/paths legacy sin referencias**: Módulos `frontend/src/modules/views/*` (legacy) no tienen importaciones en el router actual. Riesgo de divergencia de comportamiento si se reactivan por error.
2) **Endpoints duplicados o alias**: `/api/basal/dose` (alias de `/entry`) y `/api/basal/active` parecen no ser consumidos por UI moderna; podrían ser puntos de mantenimiento y confusión.

### P2
1) **Funciones API sin uso directo**: funciones en `frontend/src/lib/api.ts` no referenciadas (por ejemplo, `getBasalActive`, `getBasalCheckins`).
2) **Rutas de menú en legado**: navegación antigua en `modules/views` y algunos handlers legacy podrían activarse si se restauran rutas antiguas.

---

## Zombie Report (Top 20 candidatos)

> Criterio: (a) no referenciado, (b) feature antigua aún expuesta, (c) endpoint no consumido por frontend actual.

1. `frontend/src/modules/views/auth.js` (legacy, sin referencias actuales)
2. `frontend/src/modules/views/home.js` (legacy, sin referencias actuales)
3. `frontend/src/modules/views/bolus.js` (legacy, sin referencias actuales)
4. `frontend/src/modules/views/basal.js` (legacy, sin referencias actuales)
5. `frontend/src/modules/views/history.js` (legacy, sin referencias actuales)
6. `frontend/src/modules/views/patterns.js` (legacy, sin referencias actuales)
7. `frontend/src/modules/views/settings.js` (legacy, sin referencias actuales)
8. `frontend/src/modules/views/suggestions.js` (legacy, sin referencias actuales)
9. `frontend/src/lib/api.ts` → `getBasalActive()` (no usado en frontend)
10. `frontend/src/lib/api.ts` → `getBasalCheckins()` (no usado en frontend)
11. Backend `/api/basal/dose` (alias de `/api/basal/entry`; no usado por UI)
12. Backend `/api/basal/active` (no usado por UI)
13. Backend `/api/basal/checkins` (no usado por UI)
14. Backend `/api/basal/trigger-autoscan` (admin-only, no usado por UI)
15. Backend `/api/basal/history` (UI usa timeline; el historial clásico parece legacy)
16. Backend `app/services/export_service.py` incluye claves legacy que quizá no estén en UI directa (riesgo de desuso)
17. Frontend `frontend/src/modules/components/layout.js` (legacy, sin referencias)
18. Frontend `frontend/src/modules/views/*` tenían navegación interna propia (legacy, ya no enlazados)
19. Backend `basal_repo` paths para historial antiguo podrían quedar sin uso si la UI migra completamente a timeline
20. Flags de feature y rutas para “restaurant” pueden quedar zombis si el flag está siempre falso en producción

**Acción aplicada**
- Se eliminaron los módulos legacy `frontend/src/modules/views/*` por estar desconectados del router React actual.

## Legacy views eliminadas (detalle)

| Archivo legacy | Antes hacía (ruta/feature) | Reemplazo actual |
| --- | --- | --- |
| `frontend/src/modules/views/auth.js` | Renderizado legacy de autenticación/login. | `frontend/src/pages/LoginPage.jsx` vía `bridge.jsx` + `main.js` (`#/login`). |
| `frontend/src/modules/views/home.js` | Renderizado legacy de la home. | `frontend/src/pages/HomePage.jsx` vía `bridge.jsx` + `main.js` (`#/` y `#/home`). |
| `frontend/src/modules/views/bolus.js` | Renderizado legacy de bolos. | `frontend/src/pages/BolusPage.jsx` vía `bridge.jsx` + `main.js` (`#/bolus`). |
| `frontend/src/modules/views/basal.js` | Renderizado legacy de basal. | `frontend/src/pages/BasalPage.jsx` vía `bridge.jsx` + `main.js` (`#/basal`). |
| `frontend/src/modules/views/history.js` | Renderizado legacy de historial. | `frontend/src/pages/HistoryPage.jsx` vía `bridge.jsx` + `main.js` (`#/history`). |
| `frontend/src/modules/views/patterns.js` | Renderizado legacy de patrones. | `frontend/src/pages/PatternsPage.jsx` vía `bridge.jsx` + `main.js` (`#/patterns`). |
| `frontend/src/modules/views/settings.js` | Renderizado legacy de ajustes. | `frontend/src/pages/SettingsPage.jsx` vía `bridge.jsx` + `main.js` (`#/settings`). |
| `frontend/src/modules/views/suggestions.js` | Renderizado legacy de sugerencias. | `frontend/src/pages/SuggestionsPage.jsx` vía `bridge.jsx` + `main.js` (`#/suggestions`). |

---

## Sugerencias Report (flujo end-to-end)

### UI
- `SuggestionsPage` carga pestañas **Pendientes** y **Aceptadas**.
- Pendientes: `getSuggestions('pending')`, botón **Generar Nuevas** -> `generateSuggestions(30)`, aceptación -> modal y `acceptSuggestion` (aplica cambio local en calc params + persiste aceptación).
- Aceptadas: `getSuggestions('accepted')` + `getEvaluations` y botón de evaluación -> `evaluateSuggestion`.

### API
- `POST /api/suggestions/generate` → `generate_suggestions_service` (usa data de patrones y `ParameterSuggestion`).
- `GET /api/suggestions?status=` → `get_suggestions_service`.
- `POST /api/suggestions/{id}/accept|reject` → `resolve_suggestion_service` (actualiza estado y guarda nota).
- `POST /api/suggestions/{id}/evaluate` → `evaluate_suggestion_service`.

### Persistencia
- `parameter_suggestion` (pendiente/aceptada/rechazada) + `suggestion_evaluation` (resultados)
- No se detectó doble fuente de verdad: UI usa backend como fuente principal; el cambio en parámetros se refleja en `modules/core/store`.

### Puntos potenciales de ruptura
- La UI aplica cambios locales antes de que la API confirme aceptación (riesgo de desincronización si falla la API).
- `generateSuggestions` depende de cantidad/calidad de datos; UI ya contempla “no suggestions”.

---

## Analyze Button Bug Report

### Repro
1. Ir a **Basal** → sección **Historial (14 días)**.
2. Si hay días con `night_had_hypo = null`, aparece botón **🔍 Analizar**.
3. Click en **Analizar** → backend devuelve resultado, UI muestra alerta, pero el botón permanece en estado pendiente.

### Causa raíz
- `scan_night_service` sólo persiste resultados si `write_enabled=True`.
- El endpoint `/api/basal/night-scan` llamaba al servicio sin activar `write_enabled`, por lo que el análisis no escribía `BasalNightSummary`.

### Fix aplicado
- El endpoint ahora persiste resultados con `write_enabled=True`.
- La UI ahora muestra estado “⏳ Analizando…” y bloquea el botón mientras el análisis está en curso.
- Se añadieron logs para confirmar persistencia.

### Verificación
- Al finalizar el análisis, el timeline se recarga y la columna “Noche” cambia a **OK** o **🌙 < 70**.

---

## Checklist de verificación (local y NAS)

### Local
- Backend:
  - `pytest backend/tests/test_basal_night_scan.py`
  - Probar `/api/basal/night-scan` con fecha conocida y confirmar que `BasalNightSummary` aparece en `/api/basal/timeline`.
- Frontend:
  - Ir a **Basal** → Historial, ejecutar análisis en un día pendiente y verificar que el botón se deshabilita y desaparece al recargar la tabla.

### NAS
- Desplegar backend + frontend.
- Repetir flujo **Basal → Historial → Analizar** y confirmar persistencia al recargar página.

---

## Suposiciones
- Se asume que `NightscoutClient.get_sgv_range` devuelve datos válidos en el entorno real.
- Se asume que el frontend React es la UI principal y los módulos legacy no son consumidos en producción.
