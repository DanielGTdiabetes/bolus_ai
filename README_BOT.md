# Telegram Bot (Asistente IA Proactivo)

## Variables de entorno mínimas
- `ENABLE_TELEGRAM_BOT=true`
- `TELEGRAM_BOT_TOKEN=<token>`
- `ALLOWED_TELEGRAM_USER_ID=<id numérico>`
- `BOT_PUBLIC_URL` / `RENDER_EXTERNAL_URL` / `PUBLIC_URL` (para webhook). Si faltan, el bot usa **polling** automáticamente.
- `TELEGRAM_WEBHOOK_SECRET=<secreto>`
- Voz (opcional):
  - `ENABLE_TELEGRAM_VOICE=true`
  - `GEMINI_API_KEY` (obligatoria para voz, puede reutilizarse con `GOOGLE_API_KEY`)
  - `GEMINI_TRANSCRIBE_MODEL` (opcional, default `gemini-1.5-flash`)
  - `MAX_VOICE_SECONDS` (default 45)
  - `MAX_VOICE_MB` (default 10)

### Activar notas de voz (Gemini)
1. Configura `ENABLE_TELEGRAM_VOICE=true` y `GEMINI_API_KEY`.
2. (Opcional) Ajusta `GEMINI_TRANSCRIBE_MODEL`, `MAX_VOICE_SECONDS` o `MAX_VOICE_MB` según tu despliegue.
3. Reinicia el backend. Los logs de arranque indicarán si la voz está habilitada y el proveedor (Gemini).
4. Envía una nota de voz en Telegram: si la transcripción es dudosa, recibirás confirmación con botones ✅/✏️/❌ antes de continuar.

## Modos de entrega
- **Webhook**: si hay URL pública disponible. Se registra en `/api/webhook/telegram` con `TELEGRAM_WEBHOOK_SECRET`.
- **Polling (fallback)**: si no hay URL pública. Intervalo y timeout configurables con `TELEGRAM_POLL_INTERVAL` y `TELEGRAM_POLL_TIMEOUT`. No bloquea FastAPI.

### Health check
`curl http://localhost:8000/api/health/bot` → devuelve `enabled`, `mode (webhook|polling|disabled|error)`, `last_update_at`, `last_error`.

## Probar localmente
1. Exportar las env vars mínimas anteriores.
2. Arrancar backend: `uvicorn app.main:app --reload`.
3. Sin URL pública: el bot entra en **polling** y responde a `/start`.
4. Con URL pública: configurar `BOT_PUBLIC_URL=https://<ngrok>/...` y revisar logs de webhook.
5. Notas de voz: requiere `ENABLE_TELEGRAM_VOICE=true` y `GEMINI_API_KEY`. Si el audio supera `MAX_VOICE_SECONDS` o `MAX_VOICE_MB` se rechazará con un mensaje claro.

## Herramientas expuestas al LLM (function calling)
- `get_status_context` (BG, tendencia, IOB, COB, calidad)
- `calculate_bolus` (carbs, meal_type, split/extend)
- `calculate_correction` (objetivo opcional)
- `simulate_whatif` (carbs, horizonte)
- `get_nightscout_stats` (24h/7d)
- `set_temp_mode` (sport/sick/normal)
- `add_treatment` (registro manual, siempre con confirmación)

## Troubleshooting
- **No responde**: revisa `ENABLE_TELEGRAM_BOT`, `TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_USER_ID`. Si no hay URL pública, confirma que los logs indiquen `polling mode`.
- **Nightscout caído**: las herramientas devuelven error tipado y el bot contesta en modo degradado.
- **Whitelist**: si `ALLOWED_TELEGRAM_USER_ID` falta, el bot solo avisa en `/start` y rechaza el resto.
- **Notas de voz**:
  - Si falta `GEMINI_API_KEY` o `ENABLE_TELEGRAM_VOICE=true`, el bot avisa: “El reconocimiento de voz no está configurado, envíame el texto.”
  - Si el audio es demasiado largo/pesado, responde con el límite configurado.
  - Para transcripciones dudosas, preguntará “¿Es correcto?” con botones para confirmar, repetir o cancelar.
