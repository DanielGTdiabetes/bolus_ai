# Auditoría UI/Frontend — Settings & Config (Bolus AI)

## Resumen ejecutivo

**Qué está bien**
- El flujo principal de Settings ya está centralizado en `SettingsPage.jsx` con tabs y separa Nightscout/Dexcom/Cálculo/Bot/ML, lo que facilita el mantenimiento por área. 
- La sincronización backend↔local está diseñada con versionado en `/api/settings/` y un mecanismo de resolución de conflicto en `modules/core/store.js`.
- Nightscout ya dispone de endpoints separados para secretos (`/api/nightscout/secret`) vs. datos (`/api/nightscout/*`), lo que reduce exposición de credenciales.

**Qué duele / puntos críticos**
- Hay **duplicidad de UI** para Nightscout (`SettingsPage` vs `NightscoutSettingsPage`), lo que induce configuración divergente y rutas huérfanas.
- El **mapeo UI→backend** es parcial: varios campos del backend no se pueden configurar en UI (p. ej. `targets.low/high`, `autosens.*` avanzado, `bot.proactive.*` completo). Esto genera defaults silenciosos y confusión.
- **Defaults inconsistentes** entre frontend y backend (por ejemplo modelos de visión, umbrales bot) y un historial de envío de `version` dentro de `settings`, lo que ensucia el payload. (Arreglado en este cambio.)
- Validación insuficiente en campos críticos (URL Nightscout, rangos numéricos), provocando errores tardíos y poca claridad para el usuario.

---

## Mapeo del flujo completo de Settings

### Carga
1. **Inicialización local**: la mayoría de panels usan `getCalcParams()` (localStorage) para precargar estado. 
2. **Sync con backend**: `syncSettings()` (en `modules/core/store.js`) llama `GET /api/settings/` y migra al storage local. 
3. **Nightscout**: secretos se cargan vía `GET /api/nightscout/secret`, mientras que el filtro anti-compresión viene de `GET /api/settings/`.

### Guardado
1. **Settings generales** (ratios, bot, visión, etc): `saveCalcParams()` → `putSettings()` → `PUT /api/settings/`.
2. **Nightscout secretos**: `saveNightscoutSecret()` → `PUT /api/nightscout/secret`.
3. **Nightscout filtro**: `updateSettings()` → `PUT /api/settings/`.
4. **Dexcom**: `updateSettings()` → `PUT /api/settings/`.

---

## Campo por campo (UI → payload → backend)

### Nightscout
| UI | Payload | Backend | Observación |
|---|---|---|---|
| URL + API Secret | `/api/nightscout/secret` | `NightscoutSecrets` | Correcto. Habilitado siempre en SettingsPage. |
| Filtro compresión | `settings.nightscout.filter_*` | `NightscoutConfig` | Correcto. Guarda en settings. |
| Enabled | (solo en NightscoutSettingsPage) | `NightscoutSecrets.enabled` | **Inconsistente**: no hay toggle en SettingsPage. |

### Dexcom
| UI | Payload | Backend | Observación |
|---|---|---|---|
| enabled/username/password/region | `settings.dexcom` | `DexcomSettings` | Antes se perdía password al guardar; corregido. |

### Ratios / Targets
| UI | Payload | Backend | Observación |
|---|---|---|---|
| ICR/ISF por franja | `settings.breakfast/lunch/dinner/snack` | `settings.cr` / `settings.cf` | Migración backend hace mapping, pero el **target** por franja se reduce a `targets.mid`. |
| Target mg/dL (por franja en UI) | `settings.*.target` | `targets.mid` | **Inconsistencia**: el backend no soporta targets por franja. |

### Bot / Proactivo
| UI | Payload | Backend | Observación |
|---|---|---|---|
| premeal/combo/trend/basal | `settings.bot.proactive.*` | `BotConfig` | UI no expone `quiet_hours_*`, `sample_points_min`, `recent_*`, etc. |

### Vision / ML
| UI | Payload | Backend | Observación |
|---|---|---|---|
| provider + keys | `settings.vision` | `VisionConfig` | Defaults **difieren** (modelo gemini en frontend ≠ backend). |

---

## Zombies detectados (código muerto, duplicado o sin efecto)

1. **`NightscoutSettingsPage.jsx` (líneas ~1-105)**
   - **Por qué**: duplica configuración de Nightscout y no está enlazado desde el flujo principal (Settings tab). 
   - **Impacto**: riesgo de inconsistencias (campo `enabled` solo aquí), usuarios entrando por ruta directa con UI distinta.
   - **Propuesta**: unificar dentro de `SettingsPage` o eliminar y redirigir a `#/settings`.

2. **`saveNightscoutConfig()` en `frontend/src/lib/api.ts` (removido)**
   - **Por qué**: función sin uso y endpoint legacy. 
   - **Impacto**: ruido en API client, potencial de uso equivocado.
   - **Propuesta**: eliminado (aplicado en este cambio).

3. **Imports sin uso en SettingsPage (`fetchHealth`, `getSettingsVersion`)**
   - **Por qué**: no se referencian en la lógica actual. 
   - **Impacto**: confusión menor.
   - **Propuesta**: eliminado (aplicado).

---

## Inconsistencias UI ↔ Backend

1. **Target por franja en UI vs. `targets.mid` único en backend**
   - UI permite target distinto por desayuno/comida/cena/snack, backend solo guarda uno.
   - Resultado: el último slot editado “pisará” el target global.

2. **Defaults de Vision (Gemini Model)**
   - UI default: `gemini-2.0-flash-exp`
   - Backend default: `gemini-3-flash-preview`
   - Resultado: discrepancias si el usuario nunca guarda la configuración.

3. **Bot proactive: campos backend sin UI**
   - Ejemplo: `quiet_hours_start/end`, `sample_points_min`, `recent_carbs_minutes`.
   - Resultado: backend opera con defaults sin que el usuario lo sepa.

4. **Nightscout enabled**
   - Solo visible en `NightscoutSettingsPage`, ausente en Settings principal.
   - Resultado: los usuarios no pueden desactivar Nightscout desde la UI principal.

5. **Dexcom password**
   - Antes del fix: guardar sin password eliminaba la contraseña en backend.
   - Ahora corregido: se preserva el password si no se reescribe.

6. **Payload con `version` dentro de `settings`**
   - UI enviaba `settings.version` en el body de `PUT /api/settings/`.
   - Backend guardaba `version` como parte del settings JSON, lo que es incorrecto.
   - Corregido en este cambio.

---

## Riesgos (bugs probables) + reproducción

1. **Target por franja sobrescribe el target global**
   - **Repro**: en Settings → Cálculo, cambia target en desayuno y luego en cena. 
   - **Resultado**: el backend guarda solo el último valor en `targets.mid`. 

2. **Desincronización Nightscout enabled**
   - **Repro**: usar `NightscoutSettingsPage` para desactivar “enabled”, luego abrir `SettingsPage` (Nightscout tab).
   - **Resultado**: la UI principal no refleja ni permite cambiar el estado.

3. **Defaults inconsistentes de Vision**
   - **Repro**: usuario nunca abre tab de Visión y corre una estimación. 
   - **Resultado**: backend usa modelo distinto a lo esperado desde UI.

4. **Bot defaults invisibles**
   - **Repro**: activar Bot con UI defaults; backend aplica silencios y ventanas no configurables. 
   - **Resultado**: comportamientos inesperados sin controles en UI.

---

## Quick wins (mejoras rápidas)

1. Unificar NightscoutSettingsPage → SettingsPage (o redirigir ruta). 
2. Añadir validaciones consistentes para ratios/targets (min/max) y mensajes inline. 
3. Exponer toggles básicos para `targets.low/high` y `bot.proactive.quiet_hours_*`. 
4. Añadir “last saved”/“sync status” para settings (evitar incertidumbre).

---

## Cambios aplicados en este PR

- Eliminado `saveNightscoutConfig()` (función zombie) y limpieza de imports.
- Corregido payload de `updateSettings()` para **no** incluir `version` dentro de `settings`.
- Validación mínima en Nightscout (URL y lookback) y errores inline.
- Preservación de password Dexcom al guardar sin reescribir.

---

## Próximos pasos sugeridos

- Normalizar estructura UI ↔ backend: decidir si el target es único o por franja (y ajustar backend o UI).
- Consolidar ajustes de Vision/ML en un solo origen de verdad.
- Incrementar cobertura de validación numérica (rangos seguros para ratios, ISF, targets).

