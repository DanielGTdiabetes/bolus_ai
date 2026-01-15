# Arquitectura de Alta Disponibilidad: NAS + Render (Cold Standby)

> ⚠️ **ADVERTENCIA IMPORTANTE**
>
> **NO implementar esta arquitectura hasta que la migración al NAS esté completada y validada funcionando correctamente 24/7.**
> Este documento sirve como hoja de ruta futura para dotar al sistema de redundancia automática sin riesgo de corrupción de datos.

## 1. Objetivo

Garantizar que **Bolus AI** siga funcionando (cálculos, lecturas de Nightscout, alertas) incluso si el servidor principal (NAS) falla, utilizando la instancia de Render como respaldo de emergencia, pero **eliminando totalmente el riesgo de "Split-Brain"** (dos cerebros escribiendo datos contradictorios a la vez).

## 2. Principio Clave: "Un Solo Backend Activo"

Nunca deben existir dos backends activos escribiendo en la base de datos o enviando tratamientos a Nightscout simultáneamente.

* **NAS**: Backend Primario (Default).
* **Render**: Backend de Respaldo (Standby).
* **Base de Datos (Neon)**: Recurso compartido y "Juez Supremo" del estado.

La autoridad **NO** la decide el frontend, ni el propio NAS, ni Render. La decide un **Lock Central** en la base de datos gestionado por un árbitro externo.

## 3. Componentes de la Arquitectura

### A. Tabla `system_authority` (El Candado)

Una tabla simple en PostgreSQL que actúa como semáforo único:

```sql
CREATE TABLE system_authority (
    id INT PRIMARY KEY DEFAULT 1,
    active_backend VARCHAR(10) NOT NULL CHECK (active_backend IN ('nas', 'render')),
    last_heartbeat TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    forced_mode BOOLEAN DEFAULT FALSE -- Para mantenimientos manuales
);
```

### B. El Mecanismo de Heartbeat (Latido)

El backend que se considere "Activo" (normalmente el NAS) debe reportar su estado continuamente.

* **Frecuencia**: Cada 30-60 segundos.
* **Acción**: Actualizar el campo `last_heartbeat` en la tabla `system_authority`.
* **Condición**: Solo el backend que tiene el token de activo puede escribir el heartbeat.

### C. El Watchdog Externo (El Vigilante)

Un servicio externo independiente (fuera de la red local y fuera de Render) que verifica la salud del sistema.

* **Opciones**: GitHub Actions (Cron), UptimeRobot + Webhook, o un Microservicio Cloud Function.
* **Lógica**:
    1. Lee `last_heartbeat`.
    2. Si `NOW() - last_heartbeat > 5 minutos` → **ALARMA: EL NAS HA CAÍDO**.
    3. El Watchdog ejecuta la sentencia SQL: `UPDATE system_authority SET active_backend = 'render';`

### D. Comportamiento de las Instancias

#### Instancia Render (Standby)

* Render está desplegado pero en modo "dormido".
* Al arrancar o en cada ciclo de cron, consulta: `SELECT active_backend FROM system_authority`.
* **Si es 'nas'**: No hace NADA. No calcula, no escribe, no alerta. Solo responde `/health`.
* **Si es 'render'**: Activa todos los servicios, conecta a Nightscout y opera con normalidad.

#### Instancia NAS (Primaria)

* Opera normalmente mientras `active_backend == 'nas'`.
* Envía su heartbeat regularmente.

## 4. Flujos de Trabajo

### Failover Automático (NAS → Render)

1. Se va la luz en casa o cae Docker en el NAS.
2. El NAS deja de enviar el `heartbeat`.
3. El Watchdog detecta que el heartbeat ha expirado (> 5 min).
4. El Watchdog cambia `active_backend` a `'render'`.
5. Render (en su siguiente ciclo de chequeo) ve que ahora es el líder.
6. Render asume el control y empieza a procesar datos.
7. **Resultado**: Continuidad del servicio automática tras unos minutos de inactividad.

### Failback Manual Controlado (Render → NAS)

**CRÍTICO**: El retorno al NAS **NO** debe ser automático para evitar oscilaciones (flapping) si la conexión es inestable.

1. Vuelve la luz en casa. El NAS arranca.
2. El NAS consulta `system_authority` y ve que `active_backend == 'render'`.
3. El NAS se queda en modo **Standby** (no hace nada), esperando órdenes.
4. El Administrador (Tú) verifica que todo está estable en casa.
5. Mediante una acción manual (Botón en Frontend o comando SQL):
    * Se ejecuta: `UPDATE system_authority SET active_backend = 'nas';`
6. Render detecta el cambio y se apaga (vuelve a Standby).
7. NAS detecta el cambio y retoma el control.

## 5. Resumen de Ventajas

* ✅ **Integridad de Datos**: Imposible duplicar registros.
* ✅ **Automatización**: No dependes de intervención humana para recuperar el servicio ante un fallo.
* ✅ **Seguridad**: El NAS nunca "roba" el control de vuelta sin permiso, evitando conflictos intermitentes.
* ✅ **Simplicidad**: Lógica basada en una sola tabla SQL, sin Kubernetes ni balanceadores complejos.
