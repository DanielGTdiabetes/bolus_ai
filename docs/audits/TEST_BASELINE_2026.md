# Línea base de pruebas 2026

**Fecha:** 2026-07-11

**Rama:** `fix/test-baseline-2026`

**Base de main:** `f8e7c8943692fbf5343e6cea42829957d18b9085`

**Objetivo:** estabilizar la infraestructura de pruebas sin cambiar lógica clínica ni comportamiento de producción.

## Entorno utilizado

- BMAX, Ubuntu 24.04.3 LTS, kernel `6.17.0-23-generic`, x86_64.
- Python 3.12.3; entorno aislado `/tmp/bolus-ai-audit-venv`.
- pip 24.0; pytest 8.2.2; pytest-asyncio 0.23.7; pytest-mock 3.14.0.
- FastAPI 0.111.0; Pydantic 2.7.1; HTTPX 0.27.0; SQLAlchemy 2.0.51; aiosqlite 0.22.1.
- Node 22.22.3; npm 10.9.8; Vite 7.2.7; TypeScript 5.9.3.
- Backend aislado con SQLite temporal y secretos ficticios definidos por `backend/tests/conftest.py`.

No se arrancó NAS, Render, Neon, Telegram ni Nightscout como dependencia de prueba. No se efectuaron escrituras externas. Durante la primera colección se descubrió que pytest incluía tres scripts diagnósticos Nightscout reales situados fuera de los árboles de tests. Llegaron a ejecutar consultas GET antes de corregir `testpaths`; no realizaron escrituras. La configuración final impide su colección.

## Comandos ejecutados

```bash
git fetch origin --prune
git rev-parse HEAD
git rev-parse origin/main
/tmp/bolus-ai-audit-venv/bin/pytest --maxfail=0 -ra
/tmp/bolus-ai-audit-venv/bin/pytest --collect-only -q
/tmp/bolus-ai-audit-venv/bin/pytest --maxfail=0 -ra -W error::RuntimeWarning
/tmp/bolus-ai-audit-venv/bin/pytest backend/tests --maxfail=0 -ra -W error::RuntimeWarning
/tmp/bolus-ai-audit-venv/bin/pytest tests -ra -W error::RuntimeWarning
cd frontend && npm test
cd frontend && npm run test:simulation-payload
cd frontend && npx tsc --noEmit
cd frontend && npm run build
```

No se ejecutó cobertura: ni `pytest-cov` ni `coverage` están instalados en el entorno aislado y el repositorio no configura cobertura. No se ejecutó lint: no existe script ni configuración de linter. No se instalaron herramientas para simularlos.

## Resultado inicial

- Backend: **7 fallos, 3 errores, 284 pasadas, 2 omitidas y 8 warnings**.
- Frontend: `apiClientCore` y `bolusSimulationUtils` pasaban; `simulation_payload` fallaba.
- Build Vite: pasaba con dos warnings de módulos importados de forma estática y dinámica.
- Colección: incluía cinco scripts diagnósticos fuera de `backend/tests` y `tests`, tres con acceso Nightscout real y secretos versionados ya vinculados a SEC-001.
- SQLite registraba `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` como error de migración, aunque la creación posterior de tablas permitía continuar.

## Desglose de los siete fallos

| Caso | Causa y clasificación | Resolución en este PR |
|---|---|---|
| `test_restaurant_compare_guardrails_success` | El test enviaba form; API y cliente frontend usan JSON. **Test obsoleto / incompatibilidad contrato-implementación.** | Se alinea el test con el contrato JSON real, sin cambiar endpoint ni cálculo. |
| `test_restaurant_compare_requires_image_or_actual` | El esquema requiere `actualCarbs`; Pydantic responde 422 antes del handler. **Test obsoleto / incompatibilidad contrato-implementación.** | Se caracteriza el 422 y el campo ausente. |
| `test_callback_accept_uses_add_treatment` | Referencia al global retirado `SNAPSHOT_STORAGE`. **Test obsoleto / fixture incorrecta.** | Usa `SnapshotStore` aislado en `tmp_path`. |
| `test_exercise_callback_triggers_calc_with_payload` | Misma dependencia del global retirado. **Test obsoleto / fixture incorrecta.** | Usa la interfaz persistente actual y almacenamiento temporal. |
| `test_insulin_onset_delay_logic` | `/simulate` muta un bolo en offset 0 a +15 min, contrario al contrato expresado por el test. **Regresión real / incompatibilidad contrato-implementación.** | Sigue rojo y reproducible. No se cambia fórmula clínica; relacionado con CLIN-002 y PR-03C. |
| `test_health_connect_daily_dump_dedupes_against_recent_hermes_meal` | Una comida equivalente Hermes/Health Connect crea un segundo tratamiento. **Regresión real.** | Sigue rojo y reproducible. Se aplaza a CLIN-001 / PR-04 por riesgo clínico de falsos positivos. |
| `test_nightscout_upload_sgv_posts_expected_entry` | Comparaba bytes JSON incluyendo espacios; el objeto enviado era semánticamente idéntico. **Assertion frágil / test obsoleto.** | Compara JSON deserializado, conservando todos los campos y valores. |

## Desglose de los tres errores

Los tres casos de `backend/tests/test_bot_callbacks_recalc_context.py` fallaban en setup porque la fixture intentaba limpiar `service.SNAPSHOT_STORAGE`, eliminado al migrar a `SnapshotStore`.

| Caso | Clasificación | Resolución |
|---|---|---|
| `test_accept_manual_without_snapshot_includes_units` | Error de importación/interfaz de test obsoleta. | Fixture con `SnapshotStore(tmp_path)`. |
| `test_macro_edit_prefers_snapshot_user_id` | Fixture incorrecta / contrato interno obsoleto. | Acceso mediante `set()` y `get()`. |
| `test_set_slot_recalc_uses_snapshot_user_id` | Fixture incorrecta / contrato interno obsoleto. | Acceso mediante `set()` y `get()`. |

Estos tests conservan las assertions de ownership, macros, unidades y recálculo; no se restauró el global retirado ni se cambió producción.

## Frontend: `simulation_payload`

`buildHistoryFromSnapshot()` define `iobData.breakdown` como fuente autoritativa cuando contiene datos. En ese modo evita añadir otra vez la insulina de treatments. La fixture tenía dos bolos en breakdown, ningún bolo actual en offset 0 y exigía al menos tres. Se clasificó como **fixture/expectativa incorrecta e incompatibilidad entre el contrato documentado por el test y la implementación**.

La prueba ahora exige exactamente los dos bolos autoritativos (1.0 U y 0.5 U) y conserva las comprobaciones de carbohidratos, macros, evento solo-fibra y degradación por IOB/COB stale. No se modificó `bolusSimulationUtils.js`.

## Warnings y problemas que podían ocultar fallos

- Ocho `RuntimeWarning: coroutine ... was never awaited`: fixtures creaban sesiones completas con `AsyncMock`, convirtiendo erróneamente `db.add()` —método síncrono de SQLAlchemy— en coroutine. Se reemplazó solo ese método por `MagicMock`. En Nightscout, `response.raise_for_status()` también se modeló como síncrono. Los tests focalizados pasan con `-W error::RuntimeWarning`.
- Migración SQLite: `ADD COLUMN IF NOT EXISTS` no es compatible con la versión/dialecto usado. Continúa registrándose durante startup, pero no impide la suite. Se relaciona con DB-001 y no se corrige aquí porque exige revisar arquitectura de migraciones.
- Vite: dos warnings de mezcla de imports estáticos/dinámicos; el build es correcto. Riesgo de chunking, no fallo funcional demostrado.
- Dos skips legacy ya existentes (`test_bolus_calc.py` y `test_bugs_fix.py`); no se añadieron ni modificaron.

## Cambios realizados

- `pytest.ini` y `backend/pytest.ini`: `testpaths` explícitos para impedir recoger scripts diagnósticos o integraciones reales.
- Tests Telegram: fixtures aisladas sobre `SnapshotStore` real.
- Tests restaurante: contrato JSON actual.
- Test Nightscout: comparación semántica del payload JSON.
- Fixtures SQLAlchemy/HTTPX: métodos síncronos modelados correctamente.
- Frontend: runner `npm test` agrega los tres tests existentes; fixture `simulation_payload` alineada con la fuente autoritativa.
- Este documento de línea base.

No se modificó código de producción, fórmula clínica, defaults clínicos, deduplicación, onset, IOB, stacking, persistencia, dependencias ni configuración real.

## Resultado final

- Colección canónica: sin errores y limitada a `backend/tests` y `tests`.
- Backend completo: **2 fallos reproducibles pendientes, 287 pruebas pasadas y 2 omitidas**; cero errores de colección y cero `RuntimeWarning` con la política usada.
- `backend/tests`: **2 fallos, 262 pasadas y 2 omitidas** antes de excluir los cinco scripts; el recuento canónico final se obtiene desde la raíz.
- `tests`: **25 pasadas**.
- Frontend `npm test`: **3/3 scripts pasados**.
- `simulation_payload`: pasa.
- Typecheck: pasa.
- Build de producción: pasa con dos warnings de chunking.
- Cobertura y lint: no ejecutables con la configuración/herramientas existentes.

Los dos fallos clínicos pendientes son intencionalmente visibles. El PR debe tratarse como borrador mientras la política del repositorio exija suite completamente verde; corregirlos pertenece a PR posteriores con validación clínica.

## Diferencias BMAX, NAS, Render y CI

| Entorno | Diferencia relevante |
|---|---|
| BMAX | Python 3.12 y SQLite temporal; reproduce tests sin servicios reales. |
| NAS | Producción usa PostgreSQL y volúmenes persistentes; no se ejecutaron tests ni migraciones allí. El error SQLite no predice por sí solo PostgreSQL, pero evidencia drift. |
| Render | Build usa scripts de despliegue y PostgreSQL/Neon; no se desplegó ni validó runtime. El build Vite local sí pasó. |
| CI | No hay workflows en `.github/workflows`; tampoco matriz PostgreSQL, cobertura, lint o comando frontend canónico previo. `npm test` y `testpaths` reducen esa divergencia, pero no crean CI. |

## Riesgos pendientes y relación con hallazgos posteriores

1. **CLIN-001 / PR-04:** duplicado nutricional Hermes/Health Connect; riesgo alto para COB y contexto de bolo.
2. **CLIN-002 / PR-03C:** contrato onset y simulación; requiere decisión clínica antes de modificar offsets.
3. **DB-001:** migraciones SQLite/PostgreSQL divergentes.
4. **SEC-001:** scripts diagnósticos con secretos versionados; quedan excluidos de pytest, no saneados en este PR.
5. **CI ausente:** nada impide actualmente mergear una suite roja o ejecutar accidentalmente comandos no canónicos.
6. **Cobertura ausente:** no hay métrica reproducible de cobertura.
7. **Build chunking:** warnings de imports mixtos pendientes de evaluación separada.

## Partes no ejecutables o deliberadamente no ejecutadas

- Android/Gradle: fuera del alcance de la línea base frontend/backend.
- PostgreSQL de NAS/Neon y runtime Render: prohibidos por aislamiento y riesgo de escribir datos reales.
- Telegram, Nightscout y otros servicios externos: sustituidos por mocks/fakes en tests canónicos.
- Despliegue NAS/Render: no ejecutado durante la preparación de esta línea base.
