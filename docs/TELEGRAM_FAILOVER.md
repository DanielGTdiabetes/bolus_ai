# Telegram: NAS principal y Render de respaldo

## Problema corregido

Render seleccionaba `BotMode.DISABLED` en espera, pero conservaba un cliente capaz de enviar mensajes. El scheduler solo comprobaba `EMERGENCY_MODE`: con `false` programaba las mismas tareas que el NAS, incluido el recordatorio de basal. El bloqueo de líder tampoco coordinaba las dos instancias porque NAS y Render usan bases de datos distintas.

## Comportamiento

- El respaldo se identifica mediante `RENDER`, `APP_INSTANCE_ROLE=backup` o `APP_INSTANCE_LOCATION=render`.
- Render comprueba cada minuto `NAS_PUBLIC_URL/api/health/check`, también en espera. Una respuesta válida requiere HTTP 200 y JSON con `status: ok`.
- Con NAS disponible, estado desconocido o monitor sin comprobaciones recientes, Render no envía recordatorios de basal ni procesa mensajes entrantes. Conserva la capacidad de enviar avisos de infraestructura.
- Dos fallos consecutivos activan automáticamente su bot mediante webhook o polling. Se despierta el recordatorio de basal para comprobar si corresponde enviarlo. No es necesario cambiar `EMERGENCY_MODE`.
- El primer éxito bloquea inmediatamente los recordatorios y actualizaciones entrantes del respaldo, y devuelve el bot a espera. El aviso de recuperación estable sigue requiriendo 15 éxitos consecutivos.
- Al volver a espera, se cancelan y esperan las operaciones de Telegram que ya estaban en curso, incluido el refresco de MyFitnessPal iniciado desde una tarjeta. La cancelación no se convierte en una respuesta de error ni detiene el consumidor de polling.
- El estado activo exige recepción iniciada: webhook registrado o updater de polling en marcha. Si Telegram falla en todos los intentos de arranque, el monitor vuelve a intentarlo en su siguiente comprobación. Los intentos que siguen en curso no se reinician.
- Los permisos de envío caducan si la última comprobación tiene 120 segundos o más. La basal vuelve a comprobar el permiso justo antes del envío; `force` no evita esta protección.
- El scheduler del respaldo solo programa el monitor y la basal protegida. Las tareas periódicas de ingesta, aprendizaje, limpieza y guardian del NAS permanecen deshabilitadas en Render. La sincronización de rescate al arrancar se limita al principal.

## Configuración y despliegue

En Render, `NAS_PUBLIC_URL` debe apuntar a la URL pública del NAS. Cada instancia mantiene su propio token de Telegram. Sin URL del NAS, el respaldo permanece en espera; `EMERGENCY_MODE=true` no permite saltarse la comprobación del principal.

La corrección requiere desplegar el backend actualizado en Render y NAS. Tras desplegar, comprobar que `/api/health/bot` en Render indica `disabled` con el NAS disponible. La prueba de caída debe hacerse en una ventana acordada: confirmar activación después de dos comprobaciones fallidas y retorno a espera tras la primera respuesta correcta del NAS.

Las pruebas automatizadas usan SQLite temporal, HTTP simulado y Telegram simulado. No provocan una caída real ni envían mensajes.
