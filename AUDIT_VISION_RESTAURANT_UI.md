# Auditoría técnica + UX: Vision/Scanner y Modo Restaurante

## Parte A — Inventario y mapa del flujo

### Inventario de archivos y puntos relevantes

**Vision / Scanner / OCR / Camera / Image upload**
- Backend: `backend/app/api/vision.py` (endpoint `/api/vision/estimate`, validación, bolus recomendado, logs). 
- Backend: `backend/app/services/vision.py` (llamadas a proveedor visión, parsing/JSON, normalizaciones).
- Backend: `backend/app/models/vision.py` (esquema de respuesta, bolus, needs_user_input).
- Frontend: `frontend/src/pages/ScanPage.jsx` (UI principal de escaneo, plate builder, modo carta simple).
- Frontend: `frontend/src/lib/api.ts` (cliente `estimateCarbsFromImage`).
- Frontend: `frontend/src/components/CameraCapture.jsx` (captura de cámara nativa en restaurante).
- Frontend: `frontend/src/modules/core/store.js` (state global temporal: `tempCarbs`, `tempRestaurantSession`, etc.).

**Restaurant / Modo restaurante / Carta / Estimación / Absorción**
- Backend: `backend/app/api/restaurant.py` (endpoints `analyze_menu`, `analyze_menu_text`, `analyze_plate`, `compare_plate`, persistencia de sesión).
- Backend: `backend/app/services/restaurant.py` (prompts, parseo, guardrails, sugerencias).
- Backend: `backend/app/services/restaurant_db.py` + `backend/app/models/restaurant_session.py` (persistencia DB V2).
- Frontend: `frontend/src/components/restaurant/RestaurantSession.jsx` (flujo restaurante completo).
- Frontend: `frontend/src/lib/restaurantApi.js` (cliente API restaurante).
- Frontend: `frontend/src/hooks/useBolusCalculator.js` (crea sesión restaurante tras guardar bolo inicial).
- Frontend: `frontend/src/pages/RestaurantPage.jsx` (entrada principal).
- Frontend: `frontend/src/pages/ScanPage.jsx` (modo carta simple y puente a restaurante).

**UI / rutas / tabs**
- Rutas: `frontend/src/main.js`, `frontend/src/bridge.jsx`.
- Navegación: `frontend/src/components/layout/BottomNav.jsx`.
- Componentes UI: `frontend/src/components/ui/Atoms.jsx`.

---

### Mapa del flujo — Escáner (visión)

**Pantalla origen**
- `#/scan` → `ScanPage`.

**Acciones de usuario**
1. Selecciona modo **Un Plato**.
2. Toma foto con cámara o galería.
3. (Opcional) añade descripción extra.
4. Imagen → se analiza con IA.
5. Resultado se añade automáticamente a "Mi Plato".
6. Usuario pasa a `#/bolus` con totales.

**Llamadas API**
- `POST /api/vision/estimate` (FormData: image, meal_slot, plate_weight_grams, existing_items, image_description, etc.).

**Estados UI**
- `analyzing=true`: overlay “⏳ Analizando IA…”.
- `success`: muestra mensaje “✅ Añadido: Xg …”.
- `warning`: baja confianza o input faltante.
- `error`: mensaje detallado.
- `cancel`: “⏹️ Análisis cancelado.”

**Persistencia**
- `state.tempCarbs`, `state.tempFat`, `state.tempProtein`, `state.tempItems` (memoria de navegación a Bolus).
- `state.plateBuilder.entries` persiste plato en memoria global (no DB).

**Errores típicos y feedback**
- Imagen demasiado grande o tipo no compatible → mensaje de advertencia.
- Error backend (503/500) → mensaje explícito con detalle.
- Si `needs_user_input` → advertencia para completar datos (ej. glucosa faltante).

---

### Mapa del flujo — Modo Restaurante

**Pantalla origen**
- `#/restaurant` → `RestaurantPage` → `RestaurantSession`.

**Acciones del usuario**
1. Escanea carta o escribe descripción.
2. Recibe total esperado (HC/grasas/proteínas + warnings).
3. Calcula bolo inicial (abre `#/bolus` con `tempCarbs`).
4. Añade platos reales (foto por plato).
5. Termina la sesión → cálculo de delta.
6. Aplica sugerencia (manual, confirmada) si aplica.

**Llamadas API**
- `POST /api/restaurant/analyze_menu` (imagen de carta).
- `POST /api/restaurant/analyze_menu_text` (texto de carta).
- `POST /api/restaurant/analyze_plate` (imagen de plato).
- `POST /api/restaurant/compare_plate` (guardrails por total, sin imagen).
- Persistencia opcional:
  - `POST /api/restaurant/session/start`
  - `POST /api/restaurant/session/{id}/plate`
  - `POST /api/restaurant/session/{id}/finalize`

**Estados UI**
- `menuLoading`: carta en análisis.
- `plateLoading`: plato en análisis.
- `closing`: cierre/calculo ajuste.
- `applying`: aplicando sugerencia (requiere confirmación).

**Persistencia**
- LocalStorage: `restaurant_session_v1` (TTL 6h).
- Backend (si disponible): tabla `restaurant_sessions_v2`.

**Errores típicos y feedback**
- Sin carta estimada → error “Primero estima la carta”.
- Errores de visión → mensajes explícitos.
- Persistencia backend fallida → warning no bloqueante.

---

## Parte B — Auditoría técnica Escáner (visión)

### Hallazgos (priorizados)
**P0**
- Riesgo de doble submit / stale response: en UI no había cancelación ni guardas; una respuesta vieja podía sobrescribir la nueva. **Fix aplicado:** abort y requestId local para ignorar respuestas antiguas.

**P1**
- UX sin aviso de baja confianza o necesidad de input: se añadía plato sin contexto de incertidumbre. **Fix aplicado:** mensaje warning cuando `confidence` baja o `needs_user_input`.
- Errores genéricos en ciertos casos (sin formato/tamaño) → **Fix aplicado:** validación temprana (tipo/tamaño) y mensaje claro.

**P2**
- Observabilidad: faltaba `request-id` en logs → **Fix aplicado:** `X-Request-Id` en logs backend de visión.

### Concurrencia/Cancelación
- **Antes:** no había cancelación; doble click podía enviar múltiples requests y recibir respuestas cruzadas.
- **Ahora:** abort activo + respuesta ignorada si no coincide requestId.

### Reintentos/Timeouts
- Timeout controlado por settings backend (`vision.timeout_seconds`) ya existente.
- Se añade UI de cancelar y posibilidad de reintentar manualmente con nuevos botones.

### Manejo de nulos
- Se conservan valores default para grasas/proteínas, y advertencia si faltan datos críticos (glucosa).

---

## Parte C — Auditoría técnica Modo Restaurante

### Hallazgos
**P1**
- Copys de acción sugerida podían interpretarse como automatismo. **Fix aplicado:** texto explícito “sugerencia, no automática”.

**P2**
- Persistencia dual (local + DB) correcta pero opaca; errores backend se silencian. Mantener logs internos y warning non-blocking.

### Flujo rápido
- Carta → bolo inicial → sesión activa → platos → cierre.
- Pocos taps pero el flujo se fragmenta entre `#/restaurant` y `#/bolus` (existente, se mantiene por estabilidad).

### Edge cases
- Plato sin macros: backend devuelve 0 y warnings (no bloquea).
- Varios platos: se suman `plates[]` con totales y guardrails.

---

## Parte D — Auditoría UI/UX (fluidez e intuición)

### Checklist UX (resumen)
- Botones críticos visibles: ✅
- No hay callejón sin salida: ✅ (cancelación disponible en escáner, reset/cancel en restaurante)
- Modales no bloquean: ✅
- Loading con feedback inmediato: ✅
- Errores proponen salida: ✅ (mensajes claros, posibilidad de reintentar)
- Accesibilidad básica: ✅ (botones con estados deshabilitados y tamaños táctiles)
- Copy claro sin jerga: ✅ (advertencias explícitas)

### Cambios UI (antes/después)
- **Antes:** sin cancelación ni bloqueo de botones durante análisis.
- **Después:** botón “Cancelar”, botones deshabilitados, mensajes warning/errores claros.

---

## Parte E — Cambios implementados (fixes de bajo riesgo)

### Backend
- `vision` y `restaurant`: `X-Request-Id` en logs y response headers.
- Ajuste de mensaje de rate limit de visión para que coincida con límite real.

### Frontend
- Cancelación de análisis en `ScanPage` y prevención de doble submit.
- Guardas contra respuestas viejas (requestId).
- Validación temprana de tamaño/tipo de imagen.
- Mensajes de warning cuando baja confianza o falta input.
- Copy explícito de “sugerencia no automática” en Restaurante.

---

## Parte F — Entregables obligatorios

### Hallazgos (P0/P1/P2) con reproducción, impacto y estado
- **P0**: Doble submit / respuestas cruzadas en escáner.
  - Repro: enviar dos imágenes seguidas rápidamente; respuesta vieja pisaba estado.
  - Impacto: plato incorrecto, confusión.
  - Fix: abort + requestId. **Estado: aplicado.**

- **P1**: Estimaciones ambiguas sin aviso.
  - Repro: imagen difícil / baja confianza → no había warning.
  - Impacto: usuario confía en estimación incierta.
  - Fix: mensajes de warning en UI. **Estado: aplicado.**

- **P1**: Copy potencialmente ambiguo en ajustes de restaurante.
  - Repro: lectura de “Acción sugerida” sin aclaración.
  - Impacto: percepción de automatismo.
  - Fix: texto explícito “no automática”. **Estado: aplicado.**

- **P2**: Observabilidad limitada (sin request-id).
  - Repro: logs sin trazabilidad.
  - Impacto: debugging lento.
  - Fix: request-id en backend. **Estado: aplicado.**

### PR-style summary
- Archivos cambiados:
  - `frontend/src/pages/ScanPage.jsx`
  - `frontend/src/components/restaurant/RestaurantSession.jsx`
  - `frontend/src/lib/api.ts`
  - `frontend/src/lib/restaurantApi.js`
  - `backend/app/api/vision.py`
  - `backend/app/api/restaurant.py`
  - `backend/tests/test_api_restaurant.py`

- Qué se tocó y por qué:
  - Evitar doble submit y cancelar escaneo (robustez UX).
  - Logs con request-id y mensajes de rate limit correctos.
  - Copys de seguridad en modo restaurante.

### Cómo probarlo (pasos exactos)
1. Ir a `#/scan` → modo “Un Plato”.
2. Subir una imagen válida → ver overlay y mensaje de éxito.
3. Durante análisis, presionar “Cancelar” → confirmar mensaje de cancelación.
4. Probar un archivo no compatible → mensaje de advertencia.
5. Ir a `#/restaurant` → escanear carta o enviar texto.
6. Añadir platos, finalizar → revisar sugerencia con copy “no automática”.

### Verificación
- `pytest backend/tests/test_api_restaurant.py` (nuevo)
- `npm run test:api-client --prefix frontend`

### Checklist manual UX (10 pasos)
1. Entrar a `#/scan` y ver botones Cámara/Galería.
2. Presionar Cámara → preview visible.
3. Mientras analiza, verificar botón Cancelar.
4. Cancelar → estado vuelve a normal.
5. Subir imagen grande → advertencia tamaño.
6. Subir formato no soportado → advertencia formato.
7. Añadir plato → ver en “Mi Plato”.
8. Ir a `#/bolus` desde plato.
9. Ir a `#/restaurant` → analizar carta.
10. Terminar sesión → ver sugerencia con copy de seguridad.

### Guía de priorización
- **P0:** romper flujo, duplicar comidas, UI bloqueada, guardar sin confirmar.
- **P1:** confusión UX, mensajes ambiguos, pasos extra innecesarios.
- **P2:** refinamientos visuales y microcopy.
