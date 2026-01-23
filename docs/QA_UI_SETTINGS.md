# QA Manual — Settings UI

Este documento sirve como verificación manual cuando no existe un runner de tests automatizados (Vitest/RTL/Cypress/Playwright).

## Pre-requisitos
- Backend corriendo con autenticación activa.
- Usuario autenticado en el frontend.
- Acceso a la UI de Settings: `#/settings`.

## Caso 1 — "Settings save calls correct endpoint with correct payload"

**Objetivo:** verificar que el guardado de settings utiliza `PUT /api/settings/` con el payload esperado.

### Pasos
1. Ir a **Settings → Dexcom**.
2. Activar el toggle **Habilitar Dexcom Share**.
3. Completar `Usuario`, `Contraseña`, y seleccionar `Región`.
4. Click en **Guardar Dexcom**.

### Validaciones
- En la consola del backend (o inspección de red), confirmar:
  - Request: `PUT /api/settings/`
  - Body incluye `settings.dexcom` con:
    - `enabled: true`
    - `username`: el valor ingresado
    - `password`: el valor ingresado
    - `region`: `us` u `ous`
  - `version` enviado en el body **no** aparece dentro de `settings`.

---

## Caso 2 — "Invalid input shows error and blocks save"

**Objetivo:** validar que entradas inválidas bloquean el guardado.

### A) Nightscout URL inválida
1. Ir a **Settings → Nightscout**.
2. Introducir `mi-nightscout` (sin protocolo) como URL.
3. Click en **Guardar**.

**Resultado esperado**
- Mensaje inline: “Introduce una URL válida (http/https).”
- El guardado no debe llamar a `/api/nightscout/secret`.

### B) Lookback fuera de rango
1. En el bloque "Filtro anti-compresión", activar el filtro.
2. Introducir `-5` o `99999` en “Lookback tratamientos (min)”.
3. Click en **Guardar Ajustes**.

**Resultado esperado**
- Mensaje inline de error: “Usa un número entre 0 y 1440.”
- El guardado no debe llamar a `PUT /api/settings/`.

---

## Notas adicionales
- Si se edita Dexcom sin contraseña, el sistema debe conservar la contraseña existente (si ya estaba configurada).
- Para Nightscout, si existe secreto configurado y no se quiere cambiar, la UI debe advertir correctamente.

