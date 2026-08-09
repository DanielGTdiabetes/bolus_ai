# Fuentes de glucosa y recepcion desde el reloj

## Objetivo

Bolus AI conserva una copia local de cada lectura antes de intentar enviarla a
Nightscout. De este modo Nightscout sigue pudiendo ser la fuente seleccionada,
pero una caida de Internet o del servicio no interrumpe la continuidad local.

Las fuentes admitidas son:

- `nightscout`: lectura del Nightscout configurado para el usuario.
- `dexcom_share`: consulta a Dexcom Share con las credenciales configuradas.
- `dexcom_android`: broadcast local de la app Dexcom G7 recibido por Companion.
- `g7_direct_watch`: lectura G7 directa recibida por WtachSugar y reenviada al
  movil mediante Wear OS Data Layer.

El modo inicial sigue siendo `nightscout`. En Ajustes > Fuentes de glucosa se
puede elegir una fuente concreta o `auto`, habilitar respaldo y fijar la edad
maxima. El valor usado para una recomendacion siempre incluye su origen, edad y
estado de validacion.

Cada una de las cuatro fuentes tiene ademas un interruptor independiente. Al
desconectarla se deja de considerar inmediatamente para estado, avisos y
calculos, pero no se borran sus credenciales ni las lecturas de auditoria.

## Flujo reloj -> movil -> Bolus AI

1. WtachSugar valida la lectura recibida directamente del G7.
2. La envia al movil por la ruta Data Layer `/glucose/upstream/v1`.
3. Android Companion la guarda en su cola local.
4. Companion llama a `POST /api/integrations/mobile/glucose-entry/v2` o al
   endpoint por lotes cuando recupera conexion.
5. Bolus AI la guarda en `glucose_readings` y responde inmediatamente.
6. Si esta habilitado, un trabajo independiente la replica a Nightscout.

Si NAS no esta disponible y Companion usa la instancia de respaldo, conserva
el elemento en la cola hasta que NAS confirme el mismo `reading_uid`. Los
reenvios son idempotentes.

## Contrato Data Layer de WtachSugar

Ruta: `/glucose/upstream/v1`

Campos obligatorios:

| Campo | Tipo | Valor |
| --- | --- | --- |
| `schemaVersion` | int | `2` |
| `readingId` | string | Identificador estable de la lectura |
| `glucoseValue` | int | mg/dL |
| `timestamp` | long | Epoch en segundos medido por el sensor |
| `sensorType` | string | `G7` |
| `source` | string | `g7_direct_watch` |

Campos recomendados: `trendArrow`, `trendRate`, `sensorState`,
`displayOnly`, `historical`, `timestampUncertain`, `sensorSessionId`,
`sequence` y `sourcePackage`.

El identificador debe permanecer igual durante todos los reintentos. Lo ideal
es derivarlo de una sesion opaca del sensor y su secuencia, sin incluir ningun
dato personal ni credencial.

## API de ingesta

- `POST /api/integrations/mobile/glucose-entry/v2`: lectura individual.
- `POST /api/integrations/mobile/glucose-entries/batch`: entre 1 y 100 lecturas,
  para recuperar un hueco tras una desconexion.
- Cabecera: `X-Ingest-Key: <CGM_INGEST_KEY>`.

La clave antigua `NUTRITION_INGEST_KEY` se acepta solo para facilitar la
migracion. No se deben guardar claves en el repositorio ni enviarlas desde el
reloj: la autenticacion HTTP pertenece a Companion en el movil.

Companion permite guardar la clave exclusiva de glucosa en su almacen cifrado.
Si ese campo queda vacio utiliza la clave de integracion anterior, de modo que
las instalaciones actuales siguen funcionando durante la migracion.

## Reglas de seguridad

Una lectura no puede alimentar un calculo de insulina si es `displayOnly`, esta
en calentamiento o error, tiene hora incierta, es historica, supera la edad
configurada, esta fuera de rango o entra en conflicto con otra fuente en el
mismo instante. Se conserva para auditoria, pero queda marcada como no apta.

El backfill se presenta en el historial, pero nunca genera alarmas
retrospectivas ni corrige bolos pasados. Ante valores simultaneos distintos el
estado es `conflict` y Bolus AI exige una lectura posterior coherente.

## Despliegue

1. Configurar una `CGM_INGEST_KEY` larga y diferente en NAS y Companion.
2. Aplicar la migracion Alembic `8d1f2a3b4c5d`.
3. Desplegar primero Bolus AI y despues el APK Companion.
4. Mantener el modo `nightscout` y observar el panel de fuentes.
5. Activar `dexcom_android` como respaldo.
6. Activar `g7_direct_watch` solo cuando WtachSugar implemente y pruebe el
   contrato anterior en un G7 real.

No se debe activar el origen reloj por defecto antes de validar calentamiento,
cambio de sesion, duplicados, desconexion prolongada y reconexion NAS/backup.

## Diagnostico en Android

La pantalla Estado y diagnostico muestra un registro circular de los 30 eventos
de glucosa mas recientes y presenta los 12 ultimos: recepcion con su origen,
rechazos de validacion, intentos de envio, respuesta HTTP, instancia que acepto
la lectura, tamano de cola y errores saneados. Las claves, tokens y cabeceras de
autenticacion nunca se incluyen en ese registro.
