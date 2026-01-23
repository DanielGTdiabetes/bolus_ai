# Telegram Bot (Asistente IA Proactivo)

## Variables de entorno mínimas
- `ENABLE_TELEGRAM_BOT=true`
- `TELEGRAM_BOT_TOKEN=<token>`
- `ALLOWED_TELEGRAM_USER_ID=<id numérico>`
- URL pública para webhook (prioridad): `BOT_PUBLIC_URL` > `RENDER_EXTERNAL_URL` > `PUBLIC_URL`. Si ninguna está presente, el bot usa **polling** automáticamente.
- `TELEGRAM_WEBHOOK_SECRET=<secreto>`
- URLs de respaldo/monitor:
  - `RENDER_EXTERNAL_URL` (URL alternativa de Render para alertas de caída NAS)
  - `NAS_PUBLIC_URL` (URL principal del NAS para alertas de recuperación)
- URL pública para enlaces en notificaciones Telegram:
  - `NAS_EXTERNAL_URL` (principal, NAS) o `RENDER_EXTERNAL_URL` (fallback).
- Voz (opcional):
  - `ENABLE_TELEGRAM_VOICE=true`
  - `GEMINI_API_KEY` (obligatoria para voz, puede reutilizarse con `GOOGLE_API_KEY`)
  - `GEMINI_TRANSCRIBE_MODEL` (opcional, default `gemini-2.0-flash-exp` - *Experimental, puede cambiar*)
  - `MAX_VOICE_SECONDS` (default 45)
  - `MAX_VOICE_MB` (default 10)

### Activar notas de voz (Gemini)
1. Añade `GEMINI_API_KEY` (o `GOOGLE_API_KEY`). Si no defines `ENABLE_TELEGRAM_VOICE`, la voz se **autoactiva** cuando detecta la clave.
2. (Opcional) Forzar encendido/apagado con `ENABLE_TELEGRAM_VOICE=true|false`. Ajusta `GEMINI_TRANSCRIBE_MODEL`, `MAX_VOICE_SECONDS` o `MAX_VOICE_MB` según tu despliegue.
3. Reinicia el backend. Los logs de arranque indicarán si la voz está habilitada y el proveedor (Gemini).
4. Envía una nota de voz en Telegram: si la transcripción es dudosa, recibirás confirmación con botones ✅/✏️/❌ antes de continuar.

## Modos de entrega
- **Webhook**: si hay URL pública disponible. Se registra en `/api/webhook/telegram` con `TELEGRAM_WEBHOOK_SECRET`.
- **Polling (fallback)**: si no hay URL pública. Intervalo y timeout configurables con `TELEGRAM_POLL_INTERVAL` y `TELEGRAM_POLL_TIMEOUT`. No bloquea FastAPI.

### Webhook diagnóstico
- Verifica estado rápido: `curl https://<tu-app>.onrender.com/api/health/bot`
- Diagnóstico detallado (público, sin token): `curl https://<tu-app>.onrender.com/api/bot/telegram/webhook`
  - Revisa `mode`, `expected_webhook_url`, `public_url_source` y `telegram_webhook_info` (url, pending_update_count, last_error_message).
  - Si `error=missing_token`, falta `TELEGRAM_BOT_TOKEN`.
- Si `last_update_at` sigue `null` y Telegram no entrega:
  - Observa `pending_update_count` y `last_error_message` en `telegram_webhook_info`.
  - Refresca el registro del webhook: `curl -XPOST -H "X-Admin-Secret: <ADMIN_SHARED_SECRET>" https://<tu-app>.onrender.com/api/bot/telegram/webhook/refresh`
  - Checklist de URL pública: `BOT_PUBLIC_URL` > `RENDER_EXTERNAL_URL` > `PUBLIC_URL`.

### Health check
`curl https://<tu-app>.onrender.com/api/health/bot`

Respuesta de ejemplo:
```json
{
  "enabled": true,
  "mode": "polling",
  "reason": "missing_public_url",
  "started_at": "2024-01-01T00:00:00Z",
  "last_update_at": null,
  "last_error": null
}
```

## Probar localmente
1. Exportar las env vars mínimas anteriores.
2. Arrancar backend: `uvicorn app.main:app --reload`.
3. Sin URL pública: el bot entra en **polling** y responde a `/start`.
4. Con URL pública: configurar `BOT_PUBLIC_URL=https://<ngrok>/...` y revisar logs de webhook.
5. Notas de voz: basta con `GEMINI_API_KEY` (se autoactiva); si quieres desactivar, usa `ENABLE_TELEGRAM_VOICE=false`. Si el audio supera `MAX_VOICE_SECONDS` o `MAX_VOICE_MB` se rechazará con un mensaje claro.

### Ejercicio en recomendaciones de bolo
Cuando el bot muestra una recomendación de bolo (modo simple o dual), siempre aparece el botón **“🏃 Añadir ejercicio”** junto al resto de acciones. Tras pulsarlo, el bot pedirá intensidad y minutos, y recalculará el bolo usando el payload de ejercicio antes de actualizar el mensaje. Esto permite ajustar la recomendación de inmediato sin rehacer el cálculo desde cero.

## Herramientas expuestas al LLM (function calling)
- `get_status_context` (BG, tendencia, IOB, COB, calidad)
- `calculate_bolus` (carbs, meal_type, split/extend)
- `calculate_correction` (objetivo opcional)
- `simulate_whatif` (carbs, horizonte)
- `get_nightscout_stats` (24h/7d)
- `set_temp_mode` (sport/sick/normal)
- `add_treatment` (registro manual, siempre con confirmación)
- `check_supplies_stock` (consultar inventario agujas/sensores)
- `update_supply_quantity` (actualizar stock manualmente)
- `get_injection_site` (Consulta SIGUIENTE punto. Param opcional: `plan`='rapid'|'basal'. Devuelve imagen VERDE).
- `get_last_injection_site` (Consulta ÚLTIMO punto usado. Param opcional: `plan`. Devuelve imagen ROJA).
- `set_injection_site` (Ajuste manual del sitio actual).

## Rotación de Inyecciones
El bot incluye gestión visual automatizada de la rotación de sitios de inyección.
- **Rápida (Abdomen):** 3 puntos por zona.
- **Basal (Piernas/Glúteos):** 1 punto por zona (siempre "Punto 1").
- **Imágenes:** El bot genera imágenes dinámicas mostrando el punto exacto con un círculo de color (Verde=Siguiente, Rojo=Pasado, Azul=Selección Manual).

## Troubleshooting
- **No responde** (checklist):
  1) Abre `https://<tu-app>.onrender.com/api/health/bot` y revisa `mode` / `reason`.
  2) Revisa logs de arranque: debería indicar si está en webhook o polling y por qué.
  3) Valida `TELEGRAM_BOT_TOKEN`.
  4) Valida `ALLOWED_TELEGRAM_USER_ID` (whitelist); si falta, el bot avisará en `/start`.
  5) Si `reason=missing_public_url`, el bot está en **polling**: debería seguir respondiendo.
- **Nightscout caído**: las herramientas devuelven error tipado y el bot contesta en modo degradado.
- **Whitelist**: si `ALLOWED_TELEGRAM_USER_ID` falta, el bot solo avisa en `/start` y rechaza el resto.
- **Notas de voz**:
  - Si falta `GEMINI_API_KEY` o `ENABLE_TELEGRAM_VOICE=true`, el bot avisa: “El reconocimiento de voz no está configurado, envíame el texto.”
  - Si el audio es demasiado largo/pesado, responde con el límite configurado.
  - Para transcripciones dudosas, preguntará “¿Es correcto?” con botones para confirmar, repetir o cancelar.

## Funciones Proactivas (Jobs)
- **Morning Summary:** Resumen matutino de glucosa.
- **Basal Reminder:** Recordatorio diario de insulina lenta.
- **Supplies Check:** (Nuevo) Verificación diaria de stock de agujas y sensores. Avisa si (Agujas < 10, Sensores < 3, Reservorios < 3).

## Checklist NAS (verificación en producción)
1. Enviar un cálculo de bolo desde el bot (modo simple o dual).
2. Confirmar que aparece el botón **“🏃 Añadir ejercicio”** junto a aceptar/cancelar.
3. Revisar logs y localizar:
   - `bot_bolus_keyboard_build start: ... buttons=[...]` con el botón en la lista.
   - `bot_exercise_button gate: reason=shown motive=request_id_present`.
4. Pulsar el botón, elegir intensidad y minutos y confirmar que el mensaje de bolo se actualiza.

## TODO
- Mapear el `chat_id` de Telegram a un `username/user_id` real para recordatorios (p.ej., basal) y eliminar el fallback hardcodeado a `admin`.
