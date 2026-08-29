# Plan de resiliencia ante cortes de alimentación

## Objetivo

Evitar que un reinicio simultáneo de router, NAS y BMAX deje Bolus AI aparentemente disponible pero con glucosa obsoleta, MyFitnessPal sin disparador o servicios críticos detenidos.

Este plan mantiene estas invariantes de seguridad:

- El cálculo de bolo permanece en Bolus AI/NAS.
- La protección de IOB nunca se omite.
- Render es continuidad operativa, pero no sustituye silenciosamente al NAS como fuente de decisión.
- Una lectura CGM aceptada por Render durante una caída sigue pendiente de confirmación del NAS sin bloquear lecturas posteriores.
- Una glucosa antigua se muestra como antigua y no se usa como si fuese actual.

## Incidente observado el 29 de agosto de 2026

1. El NAS volvió a encender, pero `PortainerCE`, `bolus-ai-backend-1`, `bolus_db`, `bolus_backup_cron` y `TailScale` quedaron detenidos. Todos usaban `restart=unless-stopped`.
2. `Duckdns`, que ya usaba `restart=always`, arrancó antes de que el DNS del NAS fuese utilizable. Sus actualizaciones fallaron al resolver `www.duckdns.org` y el dominio conservó la IP pública anterior.
3. El móvil recibió Dexcom normalmente, pero acumuló 41 lecturas. Render aceptó la primera lectura, mientras la cola local la conservó esperando confirmación del NAS. El worker reenvió esa lectura duplicada y no avanzó hasta las más recientes.
4. La ingesta de MyFitnessPal sí funcionó cuando el cierre fue detectado. Las notificaciones de la última semana salieron entre 1 y 5 segundos después. El fallo matutino real es que Android agota el tiempo permitido al servicio `dataSync`; al ser `START_NOT_STICKY`, no vuelve a observar MyFitnessPal hasta que el usuario abre Bolus AI.
5. En ASUSTOR/ADM, Docker CE arranca con `--iptables=false` y delega las reglas de red en `defenderutil`. Tras el corte faltaba el enrutamiento de salida de los bridges: el host tenía Internet, pero DuckDNS y el backend no podían salir por HTTPS. `restart=always` no corrige por sí solo este estado.

## Fase 0 — Contención inmediata

- [x] Configurar `restart=always` en los contenedores activos de Portainer, Bolus AI, PostgreSQL, backup, Tailscale y DuckDNS.
- [x] Persistir `restart: always` en `deploy/nas/docker-compose.yml`.
- [x] Arrancar en orden PostgreSQL, backend, backup, Tailscale y Portainer.
- [x] Actualizar temporalmente DuckDNS de forma manual y restaurar la red de Docker CE mediante el paquete de ADM.
- [x] Verificar `GET /healthz`, acceso a Portainer y Tailscale.
- [ ] Instalar un SAI/UPS con apagado ordenado de NAS y router. Es la única protección frente a corrupción y cortes repetidos durante el arranque.

## Fase 1 — Arranque autocurativo del NAS

Crear una tarea de inicio en DSM que ejecute un verificador idempotente después de que red y Docker estén disponibles:

1. Esperar conectividad IP y resolución de `www.duckdns.org`.
2. Comprobar desde un contenedor que funcionan DNS y una conexión HTTPS. Si el host tiene salida pero los bridges no, reiniciar Docker CE desde App Central de ADM para que `defenderutil` reconstruya las reglas; no basta con reiniciar únicamente DuckDNS.
3. Arrancar los contenedores críticos en orden: `bolus_db`, `bolus-ai-backend-1`, `bolus_backup_cron`, `TailScale`, `PortainerCE`.
4. Esperar a que PostgreSQL esté `healthy` antes de iniciar el backend.
5. Reiniciar DuckDNS si su último intento terminó con error DNS o HTTPS.
6. Verificar:
   - `http://127.0.0.1:8000/healthz` devuelve 200;
   - Portainer responde en el puerto configurado;
   - Tailscale anuncia el nodo `servidor`;
   - DuckDNS resuelve a la IP pública actual.
7. Enviar una única alerta de recuperación o de fallo persistente a Telegram, sin incluir secretos.

La tarea debe poder repetirse sin recrear contenedores ni tocar volúmenes.

## Fase 2 — Continuidad de glucosa

### Corrección inmediata

Mantener dos confirmaciones por lectura:

- `backup acknowledged`: Render ya conserva la lectura.
- `primary acknowledged`: el NAS ya conserva la lectura y permite retirarla de la cola local.

Durante una caída del NAS, el worker debe enviar todas las lecturas aún no confirmadas por Render, conservarlas para reproducirlas posteriormente contra el NAS y evitar reenviar continuamente el mismo elemento. Cuando el NAS vuelva, debe vaciar la cola en orden e idempotentemente mediante `reading_uid`.

### Observabilidad requerida

La app debe mostrar por separado:

- hora y edad de la última lectura recibida desde Dexcom;
- hora de la última lectura confirmada por NAS;
- hora de la última lectura confirmada por Render;
- profundidad de cola pendiente del NAS;
- endpoint activo y motivo del failover.

Si la lectura supera el máximo de antigüedad configurado, la UI debe impedir que parezca actual y exigir glucosa manual para una corrección.

## Fase 3 — MyFitnessPal sin servicio infinito

No se debe reiniciar desde `BOOT_COMPLETED` el actual foreground service `dataSync`: Android 15+ limita estos servicios a seis horas por cada 24 horas y prohíbe iniciarlos desde `BOOT_COMPLETED`.

Diseño objetivo:

1. Detectar la transición de MyFitnessPal de forma dirigida por eventos, reutilizando el servicio de accesibilidad ya existente y limitándolo a cambios de paquete/ventana, sin leer ni almacenar el contenido de pantalla.
2. Encolar un `OneTimeWorkRequest` con red requerida para llamar a Hermes.
3. Conservar un worker periódico como reconciliación, no como detector principal inmediato.
4. Persistir el último evento observado y el identificador de sincronización para sobrevivir a muerte de proceso y reinicio.
5. Mostrar estados distintos para `ingesta completada`, `notificación pendiente` y `fallo de transporte`. `notification_status=queued` o `retry_scheduled` no debe presentarse como fallo de ingesta.

## Fase 4 — Monitorización externa y simulacros

Render o un monitor externo debe comprobar cada minuto:

- salud del NAS por dominio y Tailscale;
- coincidencia entre IP pública y DuckDNS;
- antigüedad de la última glucosa confirmada;
- crecimiento de cola CGM;
- estado del último trigger de Hermes.

Alertar solo tras varias muestras fallidas para evitar ruido, pero emitir alerta inmediata si la glucosa supera el umbral de antigüedad de seguridad.

Ejecutar trimestralmente un simulacro controlado:

1. detener el backend del NAS durante 20 minutos;
2. confirmar que Render recibe cada lectura nueva, no solo la primera;
3. arrancar el NAS y confirmar que la cola se vacía sin duplicados;
4. reiniciar NAS, router y BMAX en orden no garantizado;
5. verificar que todos los contenedores se recuperan sin Portainer;
6. comprobar un cierre de MyFitnessPal después de una noche sin abrir Bolus AI.

## Criterios de aceptación

| Escenario | Resultado obligatorio |
|---|---|
| NAS caído, Render activo | Cada lectura Dexcom llega a Render en menos de 2 minutos |
| NAS recuperado | Cola local vacía y lecturas reproducidas una sola vez por `reading_uid` |
| IP pública cambiada | DuckDNS actualizado y `/healthz` público operativo en menos de 10 minutos |
| Reinicio completo | Servicios críticos activos sin intervención de Portainer |
| Primera comida de la mañana | Un único cierre de MyFitnessPal dispara Hermes |
| Notificación Telegram aplazada | La app informa “ingesta completada; notificación pendiente” |
| Glucosa antigua | No se presenta como actual ni se usa silenciosamente para corrección |

## Runbook de comprobación rápida

1. Mirar la hora de la glucosa directa de Dexcom y compararla con Bolus AI.
2. Comprobar `https://bolus-ai.duckdns.org/healthz`.
3. Comprobar en el móvil la cola CGM y el endpoint de la última subida.
4. En el NAS, revisar estado de los seis contenedores críticos y salud de PostgreSQL.
5. Comparar la IP pública actual con el registro A de DuckDNS.
6. Probar DNS y HTTPS desde `Duckdns` y desde el backend; si falla solo dentro de Docker, recuperar Docker CE desde App Central de ADM.
7. No calcular una corrección con glucosa obsoleta; introducir el valor actual manualmente hasta restablecer el flujo.
