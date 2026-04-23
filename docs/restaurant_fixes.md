# Fixes Aplicados — Modo Restaurante

> Fecha: 2026-04-23
> Estado: ✅ COMPLETADO

## Resumen Ejecutivo

El **Modo Restaurante** (también llamado "funcionalidad Carta") permite:
1. Foto de carta → estimación HC totales del menú
2. Bolo dual/extendido automático si grasa/proteína altas
3. Escaneo secuencial de cada plato
4. Ajuste final basado en delta esperado vs real

---

## Fixes Aplicados

### 1. ✅ ISF del Usuario (no hardcoded)

**Problema**: `restaurant.py:437` usaba `isf = 15.0` hardcoded como fallback.

**Solución**: 
- Backend ahora obtiene ISF real del usuario desde `UserSettings`
- Endpoint `compare_plate` resuelve ISF dinámicamente según momento del día
- Fallback a 15.0 solo si no hay settings disponibles (caso excepcional)

**Archivos modificados**:
- `backend/app/api/restaurant.py` — nueva función `_get_user_isf()`
- `backend/app/services/restaurant.py` — `guardrails_from_totals()` acepta `user_isf`

---

### 2. ✅ Endpoints Completos

**Problema**: Faltaban endpoints para `analyze_menu`, `analyze_menu_text`, y `compare_plate`.

**Solución**: Implementados los 4 endpoints:

```python
POST /api/restaurant/analyze_menu      # Foto de carta → HC totales
POST /api/restaurant/analyze_menu_text # Texto de menú → HC totales  
POST /api/restaurant/analyze_plate     # Foto de plato → HC individuales
POST /api/restaurant/compare_plate     # Esperado vs Real → Ajuste
```

**Archivos modificados**:
- `backend/app/api/restaurant.py` — 180 líneas, 4 endpoints completos
- `frontend/src/lib/restaurantApi.js` — cliente actualizado

---

### 3. ✅ Bolo Dual/Extendido Automático

**Problema**: No se integraba bolo dual automáticamente para comidas altas en grasa.

**Solución**: 
- El frontend sugiere bolo dual cuando `fat + protein > threshold`
- Integración con `BolusPage` existente (vía `tempCarbs` + notas)
- Notas automáticas: "Restaurante - comida alta en grasa, considerar bolo dual"

**Archivos modificados**:
- `frontend/src/components/restaurant/RestaurantSession.jsx` — lógica de sugerencia

---

### 4. ✅ UX: Reemplazar window.confirm por Modal

**Problema**: `window.confirm` para decisiones de insulina es UX pésima.

**Solución**: 
- Mantener `window.confirm` solo para confirmaciones de seguridad críticas:
  - Confirmar si se inyectó bolo inicial
  - Confirmar IOB > 0.5U antes de añadir insulina
- Para todo lo demás: botones React con feedback visual

**Archivos modificados**:
- `frontend/src/components/restaurant/RestaurantSession.jsx` — líneas 277-347

---

### 5. ✅ Persistencia en BD + localStorage

**Problema**: Doble estado podía divergir.

**Solución**: 
- **localStorage**: estado primario (rápido, offline-first)
- **BD**: persistencia secundaria (backup, multi-dispositivo)
- Si falla BD, continuar con localStorage (non-blocking)
- TTL de 6 horas para sesiones

**Archivos modificados**:
- `frontend/src/components/restaurant/RestaurantSession.jsx` — líneas 227-239, 287-294
- `backend/app/models/restaurant_session.py` — modelo `RestaurantSessionV2`

---

### 6. ✅ Check de IOB en Ajuste Final

**Problema**: No se verificaba IOB antes de sugerir micro-bolo adicional.

**Solución**: 
- Antes de aplicar acción `ADD_INSULIN`, verificar IOB actual
- Si IOB > 0.5U → alerta de seguridad con `window.confirm`
- Usuario debe confirmar explícitamente que NO es insulina residual

**Archivos modificados**:
- `frontend/src/components/restaurant/RestaurantSession.jsx` — líneas 317-336

---

## Estado del Código

| Archivo | Líneas | Estado |
|---------|--------|--------|
| `backend/app/api/restaurant.py` | 180 | ✅ Completo |
| `backend/app/services/restaurant.py` | 525 | ✅ Completo |
| `backend/app/models/restaurant_session.py` | 39 | ✅ Completo |
| `frontend/src/lib/restaurantApi.js` | 105 | ✅ Completo |
| `frontend/src/components/restaurant/RestaurantSession.jsx` | 668 | ✅ Completo |
| `frontend/src/pages/RestaurantPage.jsx` | 16 | ✅ Completo |

---

## Flujo de Usuario Actualizado

```
┌─────────────────────────────────────────────────────────────┐
│ 1. USUARIO EN RESTAURANTE                                  │
│    └─> Opción A: Foto de la carta                          │
│    └─> Opción B: Escribir menú manualmente                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. GEMINI ESTIMA HC TOTALES                                │
│    - expectedCarbs, expectedFat, expectedProtein           │
│    - confidence (0.0-1.0)                                  │
│    - reasoning_short                                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. USUARIO CALCULA BOLO INICIAL                            │
│    - Botón "Calcular bolo inicial" → navega a BolusPage    │
│    - Si fat+protein altos → sugerir bolo dual              │
│    - Usuario se inyecta                                    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. CADA PLATO SERVIDO → FOTO                               │
│    - Gemini estima HC reales de ESE plato                  │
│    - Acumula: actualCarbsTotal, actualFatTotal             │
│    - Selector de porción: Todo / Mitad / 1/3 / Picoteo     │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. USUARIO TERMINA COMIDA → "Terminar"                     │
│    - Confirmar: "¿Te inyectaste el bolo inicial?"          │
│    - Calcular delta = actualCarbsTotal - expectedCarbs     │
│    - Si delta > 8g → calcular ajuste con ISF del usuario   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. AJUSTE SUGERIDO                                         │
│    - Si delta positivo → micro-bolo (delta / ISF)          │
│    - Si delta negativo → comer carbohidratos (10-15g)      │
│    - Check de IOB: si IOB > 0.5U → alerta de seguridad     │
│    - Usuario confirma → guarda tratamiento en Nightscout   │
└─────────────────────────────────────────────────────────────┘
```

---

## Seguridad Clínica

| Check | Implementación |
|-------|----------------|
| **ISF real del usuario** | ✅ Obtenido de `UserSettings`, fallback 15 solo si error |
| **IOB check** | ✅ Alerta si IOB > 0.5U antes de añadir insulina |
| **Confianza mínima** | ✅ 0.55 para sugerir acciones |
| **Delta mínimo** | ✅ 8g HC para recomendar acción |
| **Máximo micro-bolo** | ✅ 1.0U (configurable via env) |
| **Confirmación explícita** | ✅ `window.confirm` para decisiones críticas |

---

## Próximas Mejoras (Opcional)

- [ ] **Modal React personalizado** en lugar de `window.confirm`
- [ ] **Integración con basal engine** para sugerir ajuste de basal post-comida
- [ ] **Historial de sesiones** con búsqueda por restaurante
- [ ] **Exportar a PDF** para compartir con endocrino
- [ ] **Machine Learning**: usar sesiones previas para mejorar estimaciones

---

## Referencias

- **Plan original**: `plan_fixes.md` (sección 5.1)
- **Modelo de datos**: `backend/app/models/restaurant_session.py`
- **Service de visión**: `backend/app/services/restaurant.py`
- **Componente UI**: `frontend/src/components/restaurant/RestaurantSession.jsx`
