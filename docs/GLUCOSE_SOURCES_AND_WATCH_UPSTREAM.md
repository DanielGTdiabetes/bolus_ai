# Fuentes de glucosa y recepcion desde el reloj

## Objetivo

Bolus AI conserva una copia local de cada lectura antes de intentar enviarla a
Nightscout. De este modo Nightscout sigue pudiendo ser la fuente seleccionada,
pero una caida de Internet o del servicio no interrumpe la continuidad local.

Las fuentes admitidas son:

- `nightscout`: lectura del Nightscout configurado para el usuario.
- `dexcom_share`: consulta a Dexcom Share con las credenciales configuradas.
- `dexcom_android`: broadcast local de la app Dexcom G7 recibido por Companion.
- `g7_direct_watch`: lectura G7 directa recibida por WtachSugar y entregada por
  su aplicacion movil a la API de Bolus AI.

El modo inicial sigue siendo `nightscout`. En Ajustes > Fuentes de glucosa se
puede elegir una fuente concreta o `auto`, habilitar respaldo y fijar la edad
maxima. El valor usado para una recomendacion siempre incluye su origen, edad y
estado de validacion.

Cada una de las cuatro fuentes tiene ademas un interruptor independiente. Al
desconectarla se deja de considerar inmediatamente para estado, avisos y
calculos, pero no se borran sus credenciales ni las lecturas de auditoria.

## Flujo reloj -> movil -> Bolus AI

1. WtachSugar reloj valida la lectura recibida directamente del G7.
2. El movil confirma que la guardo transaccionalmente en su cola local; entonces
   el reloj puede retirarla de su outbox incluso sin Internet.
3. WtachSugar movil llama por HTTPS a
   `POST /api/integrations/mobile/glucose-entry` cuando tiene cobertura.
4. Bolus AI la guarda en `glucose_readings` y responde `201`.
5. Si la lectura ya existia responde `409`; WtachSugar movil lo trata como
   entrega completada y la retira de su cola.

Los `429` y `5xx` son reintentables. Un reintento tras perder la respuesta no
crea otra lectura.

## Contrato HTTP de WtachSugar

Ruta: `POST /api/integrations/mobile/glucose-entry`

Campos obligatorios:

| Campo | Tipo | Valor |
| --- | --- | --- |
| `schemaVersion` | int | `1` |
| `readingId` | string | Identificador estable de la lectura |
| `originInstallationId` | string | Instalacion opaca de origen |
| `outboxSequence` | int | Secuencia de la outbox movil |
| `glucoseMgDl` | int | mg/dL |
| `measuredAtEpochMillis` | long | Hora del sensor en epoch ms |
| `receivedAtWatchEpochMillis` | long | Recepcion en reloj |
| `receivedAtPhoneEpochMillis` | long | Recepcion transaccional en movil |
| `trendRateMgDlPerMinute` | number/null | Tasa de cambio |
| `trendArrow` | string | Tendencia |
| `sensorState` | int | Estado de algoritmo G7; debe ser `6` (`0x06`, utilizable) |
| `displayOnly` | bool | Lectura solo visible |
| `sensorSequence` | int | Secuencia del sensor |
| `sessionId` | string | Sesion opaca del sensor |
| `historical` | bool | Lectura de recuperacion |
| `timestampUncertain` | bool | Hora no fiable |
| `source` | string | `g7_direct_watch` |
| `decisionEligible` | bool | Debe ser exactamente `false` |

`readingId` es la clave idempotente principal. Como defensa adicional se usa
`originInstallationId + sessionId + sensorSequence`.

## API de ingesta

- `POST /api/integrations/mobile/glucose-entry`: contrato WtachSugar v1 y
  contrato Dexcom Android heredado.
- `POST /api/integrations/mobile/glucose-entry/v2`: contrato Companion v2.
- `POST /api/integrations/mobile/glucose-entries/batch`: entre 1 y 100 lecturas,
  para recuperar un hueco tras una desconexion.
- Cabecera: `X-Ingest-Key: <CGM_INGEST_KEY>`.

La clave antigua `NUTRITION_INGEST_KEY` se acepta solo para facilitar la
migracion. No se deben guardar claves en el repositorio ni enviarlas desde el
reloj: la autenticacion HTTP pertenece a la aplicacion movil emisora.

Companion permite guardar la clave exclusiva de glucosa en su almacen cifrado.
Si ese campo queda vacio utiliza la clave de integracion anterior, de modo que
las instalaciones actuales siguen funcionando durante la migracion.

## Reglas de seguridad

Las lecturas `g7_direct_watch` del contrato v1 son siempre secundarias y se
guardan con `decisionEligible=false`. No sustituyen la glucosa principal, no se
replican a Nightscout, no disparan alertas y no alimentan calculos ni
recomendaciones de insulina. `displayOnly`, calentamiento/error, hora incierta e
historico refuerzan esa exclusion.

El backfill se presenta en el historial, pero nunca genera alarmas
retrospectivas ni corrige bolos pasados. Ante valores simultaneos distintos el
estado es `conflict` y Bolus AI exige una lectura posterior coherente.

## Despliegue

1. Configurar la misma `CGM_INGEST_KEY` larga en Bolus AI y WtachSugar movil.
   En el stack NAS incluido en este repositorio ya se configura automaticamente
   un verificador SHA-256 no reversible mediante `CGM_INGEST_KEY_SHA256`; no es
   necesario publicar alli la clave original. En Render se debe crear
   manualmente `CGM_INGEST_KEY` con la clave original.
2. Aplicar la migracion Alembic `8d1f2a3b4c5d`.
3. Desplegar primero Bolus AI y despues el APK Companion.
4. Mantener el modo `nightscout` y observar el panel de fuentes.
5. Activar `dexcom_android` como respaldo.
6. Activar `g7_direct_watch` solo cuando WtachSugar implemente y pruebe el
   contrato anterior en un G7 real.

No se debe activar el origen reloj por defecto antes de validar calentamiento,
cambio de sesion, duplicados, desconexion prolongada y reconexion NAS/backup.

## Diagnostico en Android

La pantalla Estado y diagnostico de Companion muestra un registro circular de
los 30 eventos Dexcom Android mas recientes y presenta los 12 ultimos: recepcion,
rechazos de validacion, intentos de envio, respuesta HTTP, instancia que acepto
la lectura, tamano de cola y errores saneados. Las claves, tokens y cabeceras de
autenticacion nunca se incluyen en ese registro.
