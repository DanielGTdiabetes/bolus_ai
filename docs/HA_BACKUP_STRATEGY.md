# Estrategia de Alta Disponibilidad (HA) y Backup

Este documento detalla la arquitectura de **Alta Disponibilidad Híbrida** para Bolus AI, diseñada para garantizar que el servicio y los datos esenciales estén siempre disponibles, incluso en caso de fallo del hardware principal (NAS).

---

## 1. Arquitectura General

El sistema opera en un modelo **Principal (NAS) + Respaldo (Cloud/Render)**:

*   **Entorno Principal (NAS):**
    *   Ejecuta toda la lógica (`bolus_app`), base de datos (`bolus_db`), y sincronización.
    *   Es la "fuente de la verdad" para los datos históricos y tratamientos.
    *   Realiza copias de seguridad continuas hacia la nube.

*   **Entorno de Respaldo (Neon DB + Render):**
    *   **Neon DB:** Base de datos en la nube (PostgreSQL) que recibe réplicas de los datos del NAS.
    *   **Render:** Instancia de la aplicación en "standby" o "modo emergencia".

---

## 2. Sistema de Backup (NAS -> Neon)

El NAS protege los datos enviándolos regularmente a la base de datos en la nube (Neon).

### Componentes
*   **Contenedor:** `bolus_backup_cron` (definido en `docker-compose.yml`).
*   **Script:** `scripts/migration/backup_to_neon.sh`.
*   **Frecuencia:** Cada 4 horas (configurado en cron: `0 */4 * * *`).

### Lógica de Seguridad (Backup Safety Valve)
Para evitar sobrescribir datos nuevos generados en la nube (durante una emergencia) con backups antiguos del NAS, el script implementa una "Válvula de Seguridad":

1.  **Verificación Previa:** Antes de enviar datos, consulta la tabla `treatment_audit_log` en Neon.
2.  **Detección de Emergencias:** Si detecta registros creados por "Emergency Mode" en las últimas 24 horas.
3.  **Bloqueo:** **ABORTA** el backup inmediatamente.
4.  **Notificación:** Envía una alerta crítica a Telegram: _"⚠️ Backup abortado: Se detectó actividad reciente en Modo Emergencia."_

Esto garantiza que si usas el modo emergencia en la nube, el NAS no borrará tus datos nuevos al recuperarse.

---

## 3. Modo Emergencia (Render)

Si el NAS falla (corte de luz, error de disco), se activa el protocolo de emergencia en Render.

### Activación
El modo emergencia se controla mediante la variable de entorno `EMERGENCY_MODE` en Render.

*   `EMERGENCY_MODE=false` (Por defecto): La instancia de Render está en *standby*. Puede consultar datos pero **NO** ejecuta tareas de fondo (cron jobs, monitorización) para evitar conflictos con el NAS.
*   `EMERGENCY_MODE=true`: Activa la funcionalidad crítica.

### Capacidades en Modo Emergencia
Cuando está activo (`true`), la instancia en la nube habilita:

1.  **Monitorización de Glucosa:** Reactiva el trabajo en segundo plano para leer datos de Nightscout/Dexcom.
2.  **Alertas Telegram:** Vuelve a enviar alertas de hipo/hiperglucemia.
3.  **Bot Telegram (Send-Only):** Permite al bot enviar mensajes proactivos sin entrar en conflicto con el webhook del NAS (modo polling/webhook desactivado, solo envío).
4.  **Registro de Tratamientos:** Permite registrar insulina manualmente. Estos registros quedan marcados en la auditoría para activar la "Válvula de Seguridad" del backup.

### Paso a Paso: Activar Emergencia
1.  Ir al Dashboard de **Render**.
2.  Seleccionar el servicio `bolus-backend`.
3.  Ir a **Environment**.
4.  Cambiar `EMERGENCY_MODE` a `true`.
5.  Guardar. El servicio se reiniciará en modo activo.

---

## 4. Telegram Bot: Resolución de Conflictos

Uno de los problemas más comunes en arquitecturas híbridas es el conflicto del Bot de Telegram (Error 409 Conflict).

### El Problema
Telegram solo permite una conexión simultánea: o bien **Webhook** (usado por Render/Cloud) o **Polling** (usado por NAS). Si ambos intentan conectar, o si el NAS intenta hacer Polling mientras hay un Webhook activo, el bot falla.

### Solución Automática (Auto-Healing)
El sistema ahora incluye un mecanismo de **autocuración** en el código del NAS (`service.py`):

1.  **Al Inicio:** El NAS fuerza el borrado de cualquier Webhook existente antes de empezar a escuchar (Polling).
2.  **En Ejecución:** Si se detecta un error de conflicto (`Conflict`), el bot captura el error y lanza automáticamente una orden de borrado de Webhook para recuperar el control sin intervención humana.

Esto asegura que el NAS siempre tenga prioridad y "robe" el control del bot si Render lo tenía capturado.

---

## 5. Resumen de Flujos

| Estado | NAS | Neon DB | Render | Backup (NAS->Neon) |
| :--- | :--- | :--- | :--- | :--- |
| **Normal** | ✅ Activo (Polling) | ✅ Recibe Backups | 💤 Standby | ✅ Activo (4h) |
| **Fallo NAS** | ❌ Caído | ✅ Mantiene datos | ⚠️ Activar `EMERGENCY` | ❌ Detenido |
| **Recuperación**| ✅ Reiniciando... | ✅ Contiene datos Emerg.| 💤 Volver a Standby | 🛑 **Bloqueado** (Safety Valve) |

**Nota para Recuperación:** Tras un periodo de emergencia, deberás sincronizar manualmente los datos nuevos desde Neon al NAS antes de reactivar los backups automáticos.

---

## 6. Resolución de Problemas Comunes

### Error de Conexión al entrar en Render
Si al intentar entrar en la URL de Render ves un error de "Sesión caducada" o "Error de conexión":
1.  **Cierre de Sesión:** Es normal. Al cambiar de dominio (de DuckDNS a Render), el navegador no tiene tu sesión guardada.
2.  **Solución:** Ve directamente a `https://TU-APP.onrender.com/login` e inicia sesión de nuevo.
3.  **CORS:** Asegúrate de que la variable `RENDER_EXTERNAL_URL` en Render coincide exactamente con la URL que usas en el navegador.

### El Bot no responde en Render
En modo emergencia, el bot de Render está configurado como **"Send-Only"**. 
*   **SÍ** te enviará alertas de hipoglucemia y recordatorios.
*   **NO** responderá a comandos como `/bolus` o `/status`. Esto es para evitar conflictos infinitos con el Webhook/Polling del NAS. Usa la web de Render para registrar datos.
