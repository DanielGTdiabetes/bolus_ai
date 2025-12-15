# Plan de Refactorización y Mejoras - Bolus AI

Este documento sirve como bitácora de progreso para asegurar la continuidad del desarrollo entre sesiones.

## Estado Actual
- **Fecha:** 15/12/2025
- **Objetivo:** Modularizar el Frontend (main.js gigante), mejorar seguridad de datos y añadir automatización.
- **Última Acción:** Creación de este plan.

---

## Fase 1: Modularización del Frontend (Prioridad Alta)
El objetivo es dividir `frontend/src/main.js` (+3200 líneas) en módulos ES6 mantenibles.

### 1.1 Preparación de Estructura
- [x] Crear directorios:
    - `frontend/src/modules/core` (State, Router, Utils)
    - `frontend/src/modules/views` (Renderizadores de páginas)
    - `frontend/src/modules/components` (Fragmentos UI reutilizables)

### 1.2 Extracción de Lógica (Paso a Paso)
- [x] **Utils & Helpers:** Mover formateadores, fechas, validaciones a `modules/core/utils.js`.
- [x] **State Management:** Extraer el objeto `state` y sus mutadores a `modules/core/store.js`.
- [x] **Router:** Extraer lógica de navegación y auth guards a `modules/core/router.js`.

### 1.3 Extracción de Vistas (Render Functions)
- [x] **Home View:** Mover `renderHome` a `modules/views/home.js`.
- [x] **Basal View:** Mover `renderBasal` (y lógica asociada) a `modules/views/basal.js`.
- [x] **Scan/Bolus View:** Mover `renderScan`, `renderBolusResult`, `renderBolus` a `modules/views/bolus.js`.
- [x] **History & Analysis:** Mover `renderHistory`, `renderPatterns`, `renderSuggestions` a sus propios archivos (`history.js`, `patterns.js`, `suggestions.js`).
- [x] **Settings:** Mover `renderSettings` a `modules/views/settings.js`.
- [x] **Auth:** Mover `renderLogin`, `renderChangePassword` a `modules/views/auth.js`.

### 1.4 Unificación
- [x] Actualizar `main.js` para que solo importe el Router e inicialice la app.
- [x] Verificar que Vite construye correctamente.

---

## Fase 2: Seguridad y Datos (Backup)
- [x] **Exportar Datos:** Crear endpoint y botón en UI para descargar todo el historial del usuario en JSON.
- [x] **DB Resilience:** Desactivar fallback silencioso a "in-memory" en producción o añadir avisos visuales claros.

---

## Fase 3: Automatización y UX
- [x] **Background Tasks:** Investigar integración de APScheduler en backend.
- [x] **Auto-Análisis:** Tarea programada (07:00) para `scan_night_service` (Skeleton implementado + Lazy Launch en frontend para Free Tier).
- [ ] **Notificaciones Push:** (Futuro) Investigar Web Push.

---

## Registro de Sesión (Log)

| Fecha | Tarea | Estado | Notas |
|-------|-------|--------|-------|
| 15/12 | Creación de Plan | **Completado** | Roadmap inicial definido. |
