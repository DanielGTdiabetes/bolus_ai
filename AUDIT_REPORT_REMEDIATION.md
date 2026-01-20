# Auditoría de código muerto / no referenciado -> [RESUELTO]

| archivo | símbolo | por qué parece muerto | nivel de confianza | riesgo de borrarlo | Estado |
| --- | --- | --- | --- | --- | --- |
| backend/app/main_healthz_fragment.py | módulo completo | No está importado ni referenciado en main.py (healthz ya existe). | Alto | Bajo (duplicado). | **[RESUELTO] (Borrado)** |
| backend/app/bot/temp_refactor.py | _process_text_input / módulo | No se observa importación o uso desde el bot principal. | Alto | Medio (podría ser experimento temporal). | **[RESUELTO] (Borrado)** |
| frontend/src/main.js | ruta #/labs | Ruta registrada pero sin loader en bridge.jsx, siempre cae en fallback. | Alto | Bajo (ruta inválida). | **[RESUELTO] (Borrada)** |
| frontend/src/main.js | ruta #/restaurant | Ruta registrada aunque el loader sólo existe con RESTAURANT_MODE_ENABLED. | Medio | Medio (feature flag). | **[RESUELTO] (Condicionada)** |
| backend/debug_*.py | scripts de debug | Scripts sueltos en raíz de backend/ sin referencias de runtime. | Medio | Bajo (si no se usa manualmente). | Pendiente (Scripts) |
| backend/test_*.py (fuera de tests/) | scripts de prueba | Archivos de prueba en raíz fuera de tests/ podrían estar huérfanos. | Medio | Bajo (si no se ejecutan manualmente). | Pendiente (Scripts) |

# Auditoría total del repo (lectura) -> [ACTUALIZADO]

## 1) Resumen ejecutivo (ordenado por severidad)
1. **[RESUELTO] [P0] Posible doble registro de endpoint /vision/estimate** por decorador duplicado.
2. **[RESUELTO] [P1] Errores críticos silenciados** en notificaciones y bot (except/pass) que ocultan fallos. (Añadido logging).
3. **[P1] Mezcla de timestamps naive/aware** en ingestión/dedupe y modelos. (**Nota**: No modificado para evitar migraciones complejas de DB en esta fase. Se mantiene convención Naive UTC).
4. **[RESUELTO] [P1] Endpoints informativos sin auth** exponen estado del bot/jobs y capacidades. (Protegidos con CurrentUser).
5. **[RESUELTO] [P1] Middleware devuelve detalle de excepción al cliente**, potencial fuga de información en 500s. (Sanitizado).
6. **[RESUELTO] [P2] Jobs “declarados pero no programados”** (trend_alert, supplies_check). (Añadidos a `scheduler`).
7. **[RESUELTO] [P2] Ruta frontend #/labs registrada sin componente**. (Borrada).
8. **[RESUELTO] [P2] Ruta frontend #/restaurant registrada sin check de flag**. (Condicionada).
9. **[RESUELTO] [P2] Endpoint /changes/{id}/undo es stub (501)**. (Endpoint eliminado).
10. **[RESUELTO] [P3] Archivos potencialmente muertos**. (Borrados principales).

## 2) Estado de Riesgos [ACTUALIZADO]
1. [RESUELTO] Decorador duplicado en /vision/estimate.
2. [RESUELTO] Silencio de excepciones en notification_service.
3. [RESUELTO] Silencio de excepciones en bot.
4. [PENDIENTE - RIESGO BAJO] Dedupe con timestamps naive (Se asume convención actual).
5. [PENDIENTE - RIESGO BAJO] Modelo NightscoutSecrets usando DateTime naive.
6. [RESUELTO] Endpoints bot sin auth.
7. [RESUELTO] Health/jobs sin auth.
8. [RESUELTO] Error details devueltos al cliente.
9. [RESUELTO] Jobs declarados sin schedule.
10. [RESUELTO] Frontend route #/labs sin loader.

## 3) Bugs probables (P0/P1/P2) - POST REMEDIACIÓN
### P0
- **/vision/estimate doble registro** -> **[CORREGIDO]**

### P1
- **Notificaciones post-meal pueden fallar sin trazas** -> **[MITIGADO]** (Ahora loguea errores).
- **Bot suprime fallos en chequeo de Warsaw** -> **[MITIGADO]** (Ahora loguea errores).
- **Dedupe de nutrición depende de timestamps naive** -> **[NO CORREGIDO]** (Se mantiene status quo por estabilidad DB).

### P2
- **Exposición de estado interno del bot y jobs** -> **[CORREGIDO]**
- **Middleware revela errores internos** -> **[CORREGIDO]**

## 4) Código muerto confirmado vs candidato
**Confirmado:**
- [BORRADO] backend/app/main_healthz_fragment.py
- [BORRADO] backend/app/bot/temp_refactor.py
- [BORRADO] Frontend route #/labs

**Candidatos:**
- Scripts de debug en raíz de backend/ -> Se mantienen como utilidades manuales.

## 5) Zombies (flujos) - POST REMEDIACIÓN
- **Bot jobs “trend_alert” y “supplies_check”** -> **[REVIVIDOS]** (Agendados en jobs.py).
- **Frontend route #/labs** -> **[ELIMINADO]**
- **Frontend route #/restaurant con flag OFF** -> **[CORREGIDO]** (Check de flag añadido).
- **/changes/{id}/undo** -> **[ELIMINADO]**

## 7) Verificación Realizada
- [x] Decorador duplicado eliminado.
- [x] Logging añadido en bloques `except Exception: pass`.
- [x] Endpoints protegidos con `get_current_user`.
- [x] Endpoints y rutas muertas eliminadas.
- [x] Jobs faltantes añadidos al scheduler.
- [x] Pruebas unitarias actualizadas y PASANDO (`backend/tests/test_*.py`).
