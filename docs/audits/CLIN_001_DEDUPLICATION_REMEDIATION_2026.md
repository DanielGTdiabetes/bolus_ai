# CLIN-001 — Remediación de deduplicación nutricional (2026)

**Fecha:** 2026-07-11
**Base:** `main` en `2e63f2a01972deea0d9b35e120a11305b15d1c40` (merge del PR #155)
**Alcance:** únicamente CLIN-001. No se modifica onset, simulación CLIN-002, fórmulas de bolo, IOB, ratios, ISF, targets ni defaults clínicos.

## Problema e impacto

Hermes Agent y Health Connect pueden representar la misma comida con identificadores, timestamps y redondeos diferentes. El endpoint `/api/integrations/nutrition` guardaba cada evento aceptado como una fila de `treatments` con insulina cero. Un duplicado añadía carbohidratos y COB por segunda vez y podía disparar otra notificación, evaluación o tratamiento derivado.

La prueba de caracterización `test_health_connect_daily_dump_dedupes_against_recent_hermes_meal` demostraba la regresión: una comida Hermes de 28/25/73 g y el equivalente Health Connect de 27,2/24,7/73,2 g acababan en dos tratamientos.

## Flujo anterior y causa raíz

```mermaid
flowchart LR
    H[Hermes / MyFitnessPal] --> E[/nutrition]
    C[Health Connect] --> E
    E --> N[Normalización por formato]
    N --> S{notes contiene ID exacto?}
    S -- no --> F{timestamp ± ventana<br/>y carbs casi iguales?}
    F -- no --> T[(INSERT treatments)]
    F -- sí --> U[skip o enrich]
    T --> COB[COB / contexto]
    T --> TG[Telegram]
    T --> EV[Evaluaciones posteriores]
```

La identidad externa estaba incrustada en `notes`; no había una clave persistente consultable ni una relación de alias entre orígenes. El fallback usaba timestamp DB y carbohidratos, con tolerancias internas inconsistentes (consulta ±1 g y filtro final <0,5 g). Un dump de Health Connect podía conservar una hora histórica mientras Hermes había registrado la recepción reciente. Además, el patrón “buscar y después insertar” no estaba serializado.

## Fuente de verdad

La fuente de verdad clínica continúa siendo una sola fila de `treatments`. La tabla nueva `nutrition_event_identities` no contiene macros ni crea COB: únicamente relaciona alias externos hashados con el tratamiento canónico. El primer evento aceptado conserva su fila, hora, macros y procedencia; un duplicado añade un alias o enriquece campos ausentes sobre esa misma fila.

## Estrategia elegida

Orden de decisión:

1. **Identificador estable:** `usuario + origen normalizado + identificador externo` se transforma en SHA-256 (`nutrition-id-v1`). La clave única persistida resuelve reintentos, sincronizaciones repetidas y reinicios.
2. **Compatibilidad legacy:** se conserva la firma anterior en `notes` para eventos ya existentes y ediciones con timestamp idéntico.
3. **Fallback semántico entre orígenes:** solo cuando no existe alias, se comparan usuario, procedencia, tiempo y macros. Los IDs estables distintos del mismo origen se preservan como repeticiones intencionadas.
4. **Hermes reciente frente a dump Health Connect:** para MyFitnessPal/Health Connect se permite buscar una fila Hermes recibida en las últimas tres horas cuando el timestamp exportado no representa la hora de recepción.
5. **Enriquecimiento:** si el primer origen carece de grasa, proteína o fibra y el segundo las aporta, se actualiza la fila original; no se crea otra.

No se usa una clave ingenua basada solo en timestamp, nombre o suma de macros.

## Clave de idempotencia y datos persistidos

`identity_key = SHA256("nutrition-id-v1|<user>|<source>|<external-id>")`

La tabla guarda:

- clave hash única;
- `treatment_id` canónico;
- usuario y origen normalizado;
- hash del identificador externo, nunca el ID en claro;
- hash opcional de la lista normalizada de alimentos, nunca sus nombres;
- estrategia de match;
- fecha de creación.

No guarda payload, nombres de alimentos, tokens, credenciales ni macros. La huella que aparece en logs está truncada a diez caracteres.

## Ventanas y tolerancias

- match temporal normal entre orígenes: ±20 minutos;
- fallback especial Health Connect → Hermes reciente: hasta 3 horas antes de recepción y 5 minutos después;
- carbohidratos: diferencia máxima de 1,0 g;
- grasa, proteína y fibra: diferencia máxima de 1,0 g cuando ambos valores existen;
- un macro ausente se considera desconocido, no cero confirmado;
- alimentos: normalización Unicode, minúsculas, espacios y orden. Si ambos lados tienen información comparable y difieren, no se deduplica.

El endpoint redondea macros a una decimal antes del matching, igual que antes. Timestamps con zona se convierten a UTC; timestamps naive conservan la zona configurada del usuario y la DB usa UTC naive, manteniendo el contrato existente.

## Falsos positivos y repeticiones reales

Se prioriza no perder ingestas reales:

- dos IDs estables distintos del mismo origen se aceptan aunque macros y hora sean próximos;
- dos comidas en días distintos se aceptan;
- dos cafés iguales con IDs distintos se aceptan;
- alimentos diferentes bloquean el fallback cuando están disponibles;
- una edición con el mismo ID actualiza el original;
- eventos manuales ajenos a la importación no entran en el fallback, salvo procedencia Hermes legacy demostrable.

Limitación inevitable: dos orígenes diferentes, sin alimentos comparables, con macros equivalentes y dentro de la ventana pueden ser indistinguibles. Se deduplican porque es el escenario de mayor riesgo clínico; queda observable mediante `match_strategy`.

## Concurrencia, reintentos y reinicios

El bloque comprobar/relacionar/insertar se serializa por usuario hasta commit:

- PostgreSQL (NAS, Render/Neon): `pg_advisory_xact_lock`;
- SQLite (tests/fallback): `BEGIN IMMEDIATE`.

La PK única de `identity_key` aporta una segunda barrera para reintentos con el mismo ID. La identidad se confirma en la misma transacción que el tratamiento. Una respuesta HTTP perdida después del commit puede reintentarse sin crear una segunda fila. Si el proceso cae antes del commit, ni tratamiento ni alias quedan confirmados.

NAS y Render usan bases separadas. La serialización cubre cada base; no es un lock distribuido entre NAS y Neon. La arquitectura actual evita ingestión activa simultánea mediante modo de emergencia/leader y sincroniza NAS → Neon. Si ambos entornos aceptaran escrituras fuera de ese contrato, el backup seguiría siendo el punto de reconciliación no verificado.

## Persistencia, COB y derivados

COB, exportación móvil, Telegram y evaluaciones siguen consumiendo `treatments`. Como el duplicado no crea otra fila:

- carbohidratos, grasa, proteína, fibra y evento de comida no se duplican;
- calorías no se duplican indirectamente; actualmente `Treatment` no persiste un campo de calorías;
- COB se calcula una sola vez desde la fila canónica;
- no se lanza una segunda notificación para un skip;
- no se crean tratamientos/evaluaciones derivados adicionales desde el duplicado;
- Nightscout no recibe una fila pendiente duplicada (estas importaciones siguen con `is_uploaded=false`).

## Migración

La revisión `clin001_nutrition_id` crea únicamente `nutrition_event_identities` y dos índices no únicos de consulta; la PK crea el índice único de identidad. No reescribe ni bloquea prolongadamente `treatments`, no borra datos y no hace backfill masivo. Los registros antiguos se enlazan de forma perezosa cuando reaparecen.

Upgrade: `python -m alembic upgrade head` mediante `backend/start.sh`.
Rollback: `python -m alembic downgrade 2f3a4b5c6d7e` elimina solo la tabla de alias; los tratamientos originales permanecen. Tras rollback se pierde la memoria de alias nuevos, pero no datos clínicos. Upgrade/downgrade se validaron en SQLite y PostgreSQL 16 efímeros.

`alembic/env.py` ahora usa el esquema de versión `public` solo en PostgreSQL; esto permite validar migraciones SQLite sin alterar PostgreSQL.

## Observabilidad

Eventos estructurados `nutrition_dedup` indican:

- `action=accepted|duplicate`;
- estrategia;
- origen original y duplicado;
- huella truncada;
- motivo;
- ID técnico del tratamiento.

No se añaden payloads, secretos, IDs externos en claro ni nombres completos de alimentos. La corrección general de logs clínicos existentes (SEC-004) queda fuera de alcance.

## Pruebas

Cobertura añadida o conservada:

- Hermes y Health Connect: primera ingesta y reintento;
- cruce en ambos órdenes;
- timestamps iguales y con diferencias;
- redondeos pequeños y macros ausentes;
- alimentos normalizados y orden distinto;
- comidas diferentes, repeticiones intencionadas y días distintos;
- usuario/origen/ID incluidos en la clave;
- evento legacy sin ID;
- dos solicitudes simultáneas;
- persistencia tras nuevas sesiones/reintentos;
- una sola fila de tratamiento y, por tanto, un solo origen de COB/derivados.

La suite completa mantiene CLIN-002 como fallo clínico conocido y fuera de alcance.

## Flujo corregido

```mermaid
flowchart LR
    H[Hermes] --> E[/nutrition]
    C[Health Connect] --> E
    E --> N[Normalizar origen, UTC y macros]
    N --> L[Lock transaccional por usuario]
    L --> I{Alias externo existe?}
    I -- sí --> X[skip / enrich tratamiento canónico]
    I -- no --> M{Fallback cross-source<br/>tiempo + macros + alimentos}
    M -- coincide --> A[Crear alias hacia tratamiento original]
    M -- distinto --> T[Crear un treatment + alias]
    A --> O[Una sola fuente de COB y derivados]
    X --> O
    T --> O
```

## Alternativas descartadas

- índice por timestamp exacto: no tolera timezone, redondeo ni dumps históricos;
- hash solo de macros/nombre: elimina repeticiones reales;
- búsqueda y posterior insert sin lock: carrera entre workers;
- cache en memoria: se pierde al reiniciar y no coordina workers;
- añadir la lógica a Android/Hermes únicamente: no protege reintentos ni otros productores; la garantía debe estar en la fuente de verdad backend;
- unificar bases NAS/Render: fuera de alcance y no necesario para CLIN-001.

## Riesgos, rollback y limitaciones conocidas

- El fallback de tres horas se aplica solo a Health Connect contra Hermes reconocible y puede requerir ajuste con evidencia real.
- Alimentos no estaban persistidos estructuradamente en `Treatment`; para eventos nuevos se conserva solo una huella no reversible. Los eventos legacy sin ella no pueden distinguir alimentos con precisión.
- Calorías tampoco existen en `Treatment`; no se añade una nueva fuente clínica.
- No se ejecutaron escrituras ni migraciones contra NAS, Render o Neon.
- No se verificó un lock común entre NAS y Render porque usan DB separadas; depende del contrato operativo de failover.
- Rollback elimina alias y reabre la posibilidad de duplicados futuros, pero no altera tratamientos existentes.
- Las migraciones históricas requieren tablas creadas previamente cuando se parte de una DB totalmente vacía; es una limitación previa documentada, no corregida aquí.

## Comportamiento en NAS y Render

Ambos ejecutan PostgreSQL y `backend/start.sh` aplica Alembic antes de arrancar. La tabla es pequeña, aditiva y no requiere backfill. NAS sigue siendo primario; Render/Neon conserva el comportamiento de backup/emergencia. El merge puede activar despliegues automáticos, pero no se realiza despliegue manual en este trabajo.

## Elementos no verificados

- tráfico real Hermes/MyFitnessPal externo al repositorio;
- migración sobre copias reales de NAS/Neon;
- despliegue Render/NAS hasta después del merge;
- escrituras clínicas, comidas o tratamientos reales (deliberadamente no ejecutadas);
- reconciliación si NAS y Render aceptan la misma comida simultáneamente incumpliendo el modo operativo actual.
