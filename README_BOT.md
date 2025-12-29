# Telegram Bot (Asistente IA Proactivo)

## Variables de entorno mínimas
- `ENABLE_TELEGRAM_BOT=true`
- `TELEGRAM_BOT_TOKEN=<token>`
- `ALLOWED_TELEGRAM_USER_ID=<id numérico>`
- `BOT_PUBLIC_URL` / `RENDER_EXTERNAL_URL` / `PUBLIC_URL` (para webhook). Si faltan, el bot usa **polling** automáticamente.
- `TELEGRAM_WEBHOOK_SECRET=<secreto>`
- `VOICE_TRANSCRIBER_PROVIDER` + `OPENAI_API_KEY` (opcional, para notas de voz).

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
- **Notas de voz**: si falta `VOICE_TRANSCRIBER_PROVIDER` u `OPENAI_API_KEY`, el bot responde que la transcripción no está configurada.
