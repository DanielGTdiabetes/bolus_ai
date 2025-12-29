import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram import constants

from app.core import config
from app.bot import ai

# Sidecar dependencies
from pathlib import Path
from datetime import datetime, timezone, timedelta
from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.services.bolus import recommend_bolus, BolusRequestData
from app.services.injection_sites import InjectionManager

# DB Access for Settings
from app.core.db import get_engine, AsyncSession
from app.services import settings_service as svc_settings
from app.services import nightscout_secrets_service as svc_ns_secrets
from app.models.settings import UserSettings
from app.models.treatment import Treatment

async def fetch_history_context(user_settings: UserSettings, hours: int = 6) -> str:
    """Fetches simplified glucose history context using Nightscout."""
    if not user_settings.nightscout.url:
        return ""

    client = None
    try:
        client = NightscoutClient(
            base_url=user_settings.nightscout.url,
            token=user_settings.nightscout.token,
            timeout_seconds=10
        )
        
        # Calculate Time Range
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=hours)
        
        # Fetch Data (using existing get_sgv_range which accepts datetimes)
        # Assuming ~12 entries/hour (5 min interval) => hours * 12 + buffer
        count = int(hours * 12 * 1.5) 
        entries = await client.get_sgv_range(start_dt=start_time, end_dt=now, count=count)
        
        if not entries:
            return f"HISTORIA ({hours}h): No hay datos."

        # Compute Stats
        values = [e.sgv for e in entries if e.sgv is not None]
        if not values: 
            return f"HISTORIA ({hours}h): Datos vacíos."

        avg = sum(values) / len(values)
        min_v = min(values)
        max_v = max(values)
        
        # Time in Range (70-180)
        in_range = sum(1 for v in values if 70 <= v <= 180)
        tir_pct = (in_range / len(values)) * 100
        
        # Mini-Graph (Every ~30 mins)
        # We need to sort by date. Nightscout returns DESC usually? Let's sort by dateString/date.
        # entries have 'date' (epoch).
        sorted_entries = sorted(entries, key=lambda x: x.date)
        
        # Sample roughly every 30 mins
        # If we have 12 entries/hour, 30 mins = 6 entries.
        step = max(1, len(sorted_entries) // (hours * 2)) 
        
        graph_points = []
        for i in range(0, len(sorted_entries), step):
            e = sorted_entries[i]
            # Simple ascii representation? No, just numbers is cleaner for LLM
            # Maybe local time?
            # AI is good with raw lists.
            graph_points.append(str(e.sgv))
            
        # Limit graph points to ~20 to save tokens
        if len(graph_points) > 20:
             # Resample
             step2 = len(graph_points) // 20 + 1
             graph_points = graph_points[::step2]
             
        graph_str = " -> ".join(graph_points)
        
        summary = (
            f"HISTORIA ({hours}h):\n"
            f"- Promedio: {int(avg)} mg/dL\n"
            f"- Rango (70-180): {int(tir_pct)}%\n"
            f"- Min: {min_v} / Max: {max_v}\n"
            f"- Tendencia (cada ~30m): {graph_str}"
        )
        return summary
        
    except Exception as e:
        return f"HISTORIA: Error leyendo datos ({e})"
    finally:
        if client:
            await client.aclose()


logger = logging.getLogger(__name__)

# Global Application instance
_bot_app: Optional[Application] = None

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(f"Exception while handling an update: {context.error}")
    if update and isinstance(update, Update) and update.message:
        await update.message.reply_text(f"⚠️ Error interno del bot: {context.error}")

async def _check_auth(update: Update) -> bool:
    """Returns True if user is authorized."""
    allowed_id = config.get_allowed_telegram_user_id()
    if not allowed_id:
        # If no ID set, maybe allow all? Better safe than sorry: Allow NONE or Log warning
        # For this personal assistant, strict allow list is best.
        return False
        
    user_id = update.effective_user.id
    if user_id != allowed_id:
        logger.warning(f"Unauthorized access attempt from ID: {user_id}")
        await update.message.reply_text("⛔ Acceso denegado. Este bot es privado.")
        return False
    return True

async def get_bot_user_settings() -> UserSettings:
    """Helper to fetch 'admin' settings from DB (Single User assumption)."""
    settings = get_settings() # App settings
    
    
    # Try DB
    engine = get_engine()
    if engine:
        async with AsyncSession(engine) as session:
            # 1. Try 'admin'
            res = await svc_settings.get_user_settings_service("admin", session)
            db_settings = None
            
            if res and res.get("settings"):
                s = res["settings"]
                
                # Overlay Nightscout Secrets (Source of Truth)
                try:
                    ns_secret = await svc_ns_secrets.get_ns_config(session, "admin")
                    if ns_secret:
                        if "nightscout" not in s: s["nightscout"] = {}
                        s["nightscout"]["url"] = ns_secret.url
                        s["nightscout"]["token"] = ns_secret.api_secret
                        # s["nightscout"]["enabled"] = ns_secret.enabled # Respect secret enabled status? Or user pref?
                        # Usually secret table enabled is the master switch for connection.
                        # But Settings.nightscout.enabled might be the "User wants this feature" flag.
                        # Let's trust the secret config for URL/Auth.
                except Exception as e:
                    logger.warning(f"Bot failed to fetch NS secrets: {e}")

                # Check if it has NS URL (from Secrets or Legacy)
                ns = s.get("nightscout", {})
                if ns.get("url"):
                    db_settings = s
            
            # 2. If admin has no URL, try finding ANY user with a URL (Single Tenant workaround)
            if not db_settings:
                # Raw query for speed
                from sqlalchemy import text
                stmt = text("SELECT settings FROM user_settings LIMIT 5")
                rows = (await session.execute(stmt)).fetchall()
                for r in rows:
                    s = r[0] # settings json
                    if s.get("nightscout", {}).get("url"):
                         db_settings = s
                         logger.info("Bot found Settings via fallback user search.")
                         break
            
            if db_settings:
                try:
                    return UserSettings.model_validate(db_settings)
                except Exception as e:
                    logger.error(f"Failed to validate DB settings: {e}")
    
    # Fallback to JSON Store
    store = DataStore(Path(settings.data.data_dir))
    return store.load_settings()
    store = DataStore(Path(settings.data.data_dir))
    return store.load_settings()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Standard /start command."""
    if not await _check_auth(update): return
    
    user = update.effective_user
    await update.message.reply_text(
        f"Hola {user.first_name}! Soy tu asistente de diabetes (Bolus AI).\n"
        "Estoy listo w/ Gemini 3.0. Envíame una foto de comida o pregúntame algo."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Text Handler - The Python Router."""
    if not await _check_auth(update): return
    
    text = update.message.text
    if not text: return

    # --- Python Logic Layer (Router) ---
    cmd = text.lower().strip()
    
    if cmd == "ping":
        await update.message.reply_text("Pong! 🏓 (Python Server is alive)")
        return
        
    if cmd in ["status", "estado"]:
        # Future: Call Nightscout service
        await update.message.reply_text("📉 Estado: Simulando conexión a Nightscout... (Todo OK)")
        return

    if cmd == "debug":
        # Diagnostics
        out = ["🕵️ **Diagnóstico Avanzado**"]
        
        # 1. Global Env
        settings = get_settings()
        env_url = settings.nightscout.base_url
        out.append(f"🌍 **ENV Var URL:** `{env_url}`")
        
        # 2. User Settings (DB)
        try:
            bot_settings = await get_bot_user_settings()
            ns = bot_settings.nightscout
            out.append(f"👤 **User DB URL:** `{ns.url}` (Enabled: {ns.enabled})")
            
            # DB Discovery Detail
            engine = get_engine()
            if engine:
                async with AsyncSession(engine) as session:
                    # List all users
                    from sqlalchemy import text
                    stmt = text("SELECT user_id, settings FROM user_settings")
                    rows = (await session.execute(stmt)).fetchall()
                    out.append(f"📊 **Usuarios en DB:** {len(rows)}")
                    for r in rows:
                        uid = r.user_id
                        raw = r.settings
                        ns_raw = raw.get("nightscout", {})
                        url_raw = ns_raw.get("url", "EMPTY")
                        out.append(f"- User `{uid}`: NS_URL=`{url_raw}`")
            else:
                out.append("⚠️ **DB Desconectada.**")

            # 3. Connection Test
            target_url = ns.url or (str(env_url) if env_url else None)
            
            if target_url:
                out.append(f"📡 **Probando:** `{target_url}`")
                client = NightscoutClient(target_url, ns.token, timeout_seconds=5)
                try:
                    sgv = await client.get_latest_sgv()
                    out.append(f"✅ **Conexión EXITOSA**")
                    out.append(f"SGV: {sgv.sgv} mg/dL")
                except Exception as e:
                     out.append(f"❌ **Fallo:** `{e}`")
                finally:
                    await client.aclose()
            else:
                 out.append("🛑 **No hay URL para probar.**")

            # 4. Check DB History
            engine = get_engine()
            if engine:
                 async with AsyncSession(engine) as session:
                    from sqlalchemy import text
                    stmt = text("SELECT created_at, insulin FROM treatments ORDER BY created_at DESC LIMIT 1")
                    row = (await session.execute(stmt)).fetchone() 
                    if row:
                         out.append(f"💉 **Último Bolo (DB):** {row.insulin} U ({row.created_at.strftime('%H:%M')})")
                    else:
                         out.append(f"💉 **Último Bolo (DB):** (Vacío)")
            else:
                 out.append("⚠️ **Sin acceso a Historial DB**")

        except Exception as e:
            out.append(f"💥 **Error Script:** `{e}`")
            
        # Send without markdown to avoid parsing errors (underscores in URLs, etc.)
        await update.message.reply_text("\n".join(out))
        return

    # --- AI Layer (Fallthrough) ---
    # Show typing action
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
    
    # Decide Model Mode (Flash vs Pro)
    # Heuristic: Short text -> Flash. "Analiza", "Por que" -> Pro?
    # For now, strictly Flash to save tokens unless requested.
    mode = "flash" 
    if "profundo" in cmd or "piensa" in cmd:
        mode = "pro"
        await update.message.reply_text("🧠 Activando Gemini 3.0 Pro (Razonamiento)...")

    # Context Injection (Full Access)
    context_lines = []
    
    try:
        settings = get_settings()
        store = DataStore(Path(settings.data.data_dir))
        # user_settings = store.load_settings() # OLD
        user_settings = await get_bot_user_settings() # NEW (DB)
        
        # 1. Glucose (Nightscout)
        # 1. Glucose (Nightscout)
        ns_client = None
        # Robust check: If URL exists, try to use it even if enabled=False (warn user)
        if user_settings.nightscout.url:
             if not user_settings.nightscout.enabled:
                 logger.warning("[HandeMsg] Nightscout DISABLED but URL present. Attempting connection.")
             
             ns_client = NightscoutClient(
                base_url=user_settings.nightscout.url,
                token=user_settings.nightscout.token,
                timeout_seconds=5
             )
        
        if ns_client:
            try:
                sgv = await ns_client.get_latest_sgv()
                arrow = sgv.direction or ""
                delta = f"{sgv.delta:+.1f}" if sgv.delta is not None else "?"
                context_lines.append(f"GLUCOSA: {sgv.sgv} {user_settings.nightscout.units} ({arrow}) Delta: {delta}")
            except Exception as e:
                logger.error(f"Bot handle_message failed to get SGV: {e}")
                context_lines.append(f"GLUCOSA: Error leyendo ({str(e)})")
        else:
            context_lines.append("GLUCOSA: No Configurada (Falta URL)")

        # 2. IOB & COB
        now_utc = datetime.now(timezone.utc)
        try:
            iob_u, _, _, _ = await compute_iob_from_sources(now_utc, user_settings, ns_client, store)
            cob_g = await compute_cob_from_sources(now_utc, ns_client, store) # Estimate
            
            context_lines.append(f"IOB (Insulina Activa): {iob_u:.2f} U")
            context_lines.append(f"COB (Carbos Activos): {cob_g:.0f} g (aprox)")
        except Exception as e:
            logger.warning(f"Error computing IOB/COB: {e}")

        # 3. Settings Snapshot (Key stats)
        # Use current time to find relevant CR/ISF (approximate to 'now' slot)
        # Simple Logic: morning/afternoon/night
        h = now_utc.hour + 1 # CET Winter (UTC+1). TODO: Dynamic User Timezone
        
        context_lines.append("\nCONF USUARIO:")
        context_lines.append(f"- ISF (Sensibilidad): {user_settings.cf.breakfast} (D) / {user_settings.cf.lunch} (A) / {user_settings.cf.dinner} (C)")
        context_lines.append(f"- CR (Ratio): {user_settings.cr.breakfast} (D) / {user_settings.cr.lunch} (A) / {user_settings.cr.dinner} (C)")
        context_lines.append(f"- Objetivo: {user_settings.targets.mid} mg/dL")
        context_lines.append(f"- DIA (Duración Insulina): {user_settings.iob.dia_hours:.1f} horas")
        context_lines.append(f"- Pico Insulina: {user_settings.iob.peak_minutes} min")
        
        context_lines.append(f"- Basal Típica: {user_settings.tdd_u} U/día (aprox)")

        # 4. Injection Sites
        im = InjectionManager(store)
        next_bolus = im.get_next_site("bolus")
        next_basal = im.get_next_site("basal")
        context_lines.append("\nSITIOS INYECCIÓN:")
        context_lines.append(f"- Bolus (Siguiente): {next_bolus}")
        context_lines.append(f"- Basal (Siguiente): {next_basal}")

        if ns_client:
            await ns_client.aclose()

            # 5. Recent Treatments (DB) - Last 3
        try:
             # Re-use engine if available (should be, we checked settings)
             engine = get_engine()
             if engine:
                async with AsyncSession(engine) as session:
                    from sqlalchemy import text
                    # Fetch latest bolus
                    stmt = text("SELECT created_at, insulin, event_type, carbs, notes FROM treatments ORDER BY created_at DESC LIMIT 3")
                    rows = (await session.execute(stmt)).fetchall()
                    
                    context_lines.append(f"\nÚLTIMOS REGISTROS (DB):")
                    if rows:
                        for row in rows:
                            t_delta = (now_utc.replace(tzinfo=None) - row.created_at).total_seconds() / 60
                            info = f"{row.insulin}U"
                            if row.carbs: info += f" + {row.carbs}g"
                            if row.notes: info += f" ({row.notes})"
                            context_lines.append(f"- {row.event_type}: {info} hace {int(t_delta)} min")
                    else:
                        context_lines.append("Ninguno reciente")
        except Exception as e:
            logger.error(f"Failed to fetch last treatment: {e}")
            
    except Exception as e:
        logger.warning(f"Bot failed to fetch detailed context: {e}")
        context_lines.append(f"ERROR LECTURA DATOS: {e}")

# --- AI Tools Definition ---
AI_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "add_treatment",
                "description": "Registrar una comida (carbohidratos) o una dosis de insulina. El bot calculará la dosis necesaria y pedirá confirmación.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "carbs": {"type": "NUMBER", "description": "Gramos de carbohidratos (opcional)"},
                        "insulin": {"type": "NUMBER", "description": "Unidades de insulina (opcional, si se especifica anula el cálculo)"},
                        "notes": {"type": "STRING", "description": "Notas opcionales (ej: 'Pizza', 'Corrección')"}
                    }
                }
            }
        ]
    }
]

async def _handle_add_treatment_tool(update: Update, context: ContextTypes.DEFAULT_TYPE, args: dict) -> None:
    """
    Called when AI asks to 'add_treatment'.
    We calculate recommendations (if needed) and show a confirmation card.
    """
    carbs = float(args.get("carbs", 0) or 0)
    insulin_req = args.get("insulin")
    insulin_req = float(insulin_req) if insulin_req is not None else None
    notes = args.get("notes", "Via Chat")
    
    chat_id = update.effective_chat.id
    
    await update.message.reply_text("⚙️ Procesando solicitud de tratamiento...")
    
    # 1. Fetch Context
    settings = get_settings()
    store = DataStore(Path(settings.data.data_dir))
    user_settings = await get_bot_user_settings()
    
    bg_val = None
    iob_u = 0.0
    ns_client = None
    
    if user_settings.nightscout.url:
         ns_client = NightscoutClient(
            base_url=user_settings.nightscout.url,
            token=user_settings.nightscout.token,
            timeout_seconds=5
         )
    
    try:
        # Fetch BG
        if ns_client:
            try:
                sgv = await ns_client.get_latest_sgv()
                bg_val = float(sgv.sgv)
            except Exception: pass
            
        # Fallback Local DB
        if bg_val is None:
            try:
                engine = get_engine()
                if engine:
                    async with AsyncSession(engine) as session:
                        from sqlalchemy import text
                        stmt = text("SELECT sgv FROM entries ORDER BY date_string DESC LIMIT 1") 
                        row = (await session.execute(stmt)).fetchone()
                        if row: bg_val = float(row.sgv)
            except Exception: pass

        # Calc IOB
        now_utc = datetime.now(timezone.utc)
        try:
            iob_u, _, _, _ = await compute_iob_from_sources(now_utc, user_settings, ns_client, store)
        except Exception: pass
        
    finally:
        if ns_client: await ns_client.aclose()
        
    # 2. Recommendation Logic
    rec_u = 0.0
    reason = "Manual"
    
    # Determine Meal Slot
    h = datetime.now(timezone.utc).hour + 1 # Approx local time fix (Winter CET)
    slot = "lunch"
    if 5 <= h < 11: slot = "breakfast"
    elif 11 <= h < 17: slot = "lunch"
    elif 17 <= h < 23: slot = "dinner"
    else: slot = "snack"

    if insulin_req is not None:
        rec_u = insulin_req
        reason = f"Petición explícita ({notes})"
    else:
        # Run Calculator
        eff_bg = bg_val if bg_val else user_settings.targets.mid
        req_data = BolusRequestData(
            carbs_g=carbs,
            bg_mgdl=eff_bg,
            meal_slot=slot
        )
        rec = recommend_bolus(req_data, user_settings, iob_u)
        rec_u = rec.upfront_u
        reason = rec.explain[0]

    # 3. Send Card
    # Get Site
    injection_mgr = InjectionManager(store)
    next_site = injection_mgr.get_next_site("bolus")
    
    bg_str = f"{bg_val} mg/dL" if bg_val else "???"
    iob_str = f"({iob_u:.1f}u IOB)" if iob_u > 0 else ""
    
    msg_text = (
        f"📝 **Confirmar Tratamiento**\n"
        f"Carbos: **{carbs}g**\n"
        f"Notas: _{notes}_\n"
        f"Glucosa: {bg_str} {iob_str}\n\n"
        f"💉 **Sugerencia: {rec_u} U**\n"
        f"📍 **Lugar:** {next_site}\n"
        f"_Razón: {reason}_"
    )
    
    # Use special callback prefix to handle this confirmation
    # Logic is same as proactive notification: save treatment.
    # We can reuse 'bolus_confirm_' but we lose 'carbs' info if we use the old callback which hardcodes carbs=0.
    # Old callback 'bolus_confirm_{units}' assumes carbs were already logged via 'on_new_meal_received' (external).
    # HERE, carbs are NOT saved yet.
    # So we need a NEW callback or modified one.
    # Let's use 'chat_bolus_{units}_{carbs}'
    # We will need to update handle_callback too.
    
    keyboard = [
        [
            InlineKeyboardButton(f"✅ Registrar {rec_u} U", callback_data=f"chat_bolus_{rec_u}_{carbs}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="ignore")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode="Markdown")


    # --- History Injection (Intelligent Context) ---
    # Heuristic: If user talks about past/trends, inject history.
    # Words: noche, ayer, resumen, tendencia, subida, bajada, dia, durmiendo
    hist_keywords = ["noche", "ayer", "resumen", "tendencia", "subida", "bajada", "dia", "durmiendo", "pasó", "paso"]
    if any(k in cmd for k in hist_keywords):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
        # Default 8h (Night) or 24h if "ayer"
        h_lookback = 24 if "ayer" in cmd else 8
        try:
            hist_summary = await fetch_history_context(user_settings, hours=h_lookback)
            if hist_summary:
                context_lines.append("\n" + hist_summary)
        except Exception as e:
            logger.error(f"Failed to inject history: {e}")

    try:
        context_str = "\n".join(context_lines)
        
        logger.info("🤖 Calling AI (Chat Completion)...")
        response_data = await ai.chat_completion(
            text, 
            context=context_str, 
            mode=mode, 
            tools=AI_TOOLS
        )
        logger.info(f"🤖 AI Response received: {str(response_data)[:100]}...")

        # Handle Response
        did_action = False
        
        if response_data.get("function_call"):
            fn = response_data["function_call"]
            name = fn["name"]
            args = fn["args"]
            
            logger.info(f"AI triggered tool: {name} with {args}")
            
            if name == "add_treatment":
                await _handle_add_treatment_tool(update, context, args)
                did_action = True
        
        # Always reply with text if present (AI often explains "He preparado la confirmación...")
        # or if no action was taken
        if response_data.get("text"):
            await update.message.reply_text(response_data["text"])
        elif not did_action:
            # Fallback if AI returned nothing (rare)
            await update.message.reply_text("🤔 (Sin respuesta)")
            
    except Exception as e:
        logger.error(f"Error AI processing: {e}")
        await update.message.reply_text("⚠️ Hubo un error procesando tu mensaje. Intenta de nuevo en unos segundos.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photo Handler - Vision Layer."""
    if not await _check_auth(update): return
    
    photo = update.message.photo[-1] # Largest size
    
    # Notify user
    await update.message.reply_text("👀 Analizando plato con Gemini Vision...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)

    try:
        # Download file (in memory)
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        
        # Call AI
        json_response = await ai.analyze_image(image_bytes)
        
        # Reply (formatting the JSON for readability)
        await update.message.reply_text(f"🍽️ Resultado:\n{json_response}")
        
    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await update.message.reply_text("❌ Error procesando la imagen.")

def create_bot_app() -> Application:
    """Factory to create and configure the PTB Application."""
    token = config.get_telegram_bot_token()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Bot will not run.")
        return None

    application = Application.builder().token(token).build()

    # Register Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Error Handler
    application.add_error_handler(error_handler)
    
    return application

async def initialize() -> None:
    """
    Called on FastAPI startup.
    Sets up the webhook if enabled.
    """
    global _bot_app
    
    if not config.is_telegram_bot_enabled():
        logger.info("Telegram Bot is DISABLED via config.")
        return

    logger.info("Initializing Telegram Bot...")
    _bot_app = create_bot_app()
    
    if not _bot_app:
        return

    # Initialize the app (coroutines)
    await _bot_app.initialize()
    await _bot_app.start()

    # Set Webhook logic
    # We need the public URL. In Render, we can get it from env RENDER_EXTERNAL_URL or manual config.
    public_url = config.get_env("RENDER_EXTERNAL_URL") or config.get_env("public_url")
    webhook_secret = config.get_telegram_webhook_secret()
    
    if public_url:
        webhook_url = f"{public_url}/api/webhook/telegram"
        logger.info(f"Setting Telegram Webhook to: {webhook_url}")
        await _bot_app.bot.set_webhook(url=webhook_url, secret_token=webhook_secret)
    else:
        logger.warning("No Public URL found. Webhook NOT set. Bot may not receive updates.")

async def shutdown() -> None:
    """Called on FastAPI shutdown."""
    global _bot_app
    if _bot_app:
        logger.info("Shutting down Telegram Bot...")
        await _bot_app.stop()
        await _bot_app.shutdown()

async def process_update(update_data: dict) -> None:
    """
    Entry point for the Webhook Router.
    Feeds the update dict into the PTB Application.
    """
    if not _bot_app:
        return
        
    try:
        update = Update.de_json(update_data, _bot_app.bot)
        await _bot_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing Telegram update: {e}")

async def on_new_meal_received(carbs: float, source: str) -> None:
    """
    Called by integrations.py when a new meal is ingested.
    Triggers a proactive notification.
    """
    global _bot_app
    if not _bot_app:
        return

    chat_id = config.get_allowed_telegram_user_id()
    if not chat_id:
        return

    logger.info(f"Bot proactively notifying meal: {carbs}g from {source}")
    
    # 1. Gather Context
    settings = get_settings()
    store = DataStore(Path(settings.data.data_dir))
    user_settings = await get_bot_user_settings() # NEW (DB)
    
    bg_val = None
    iob_u = 0.0
    ns_client = None
    
    # Init NS Client
    # Init NS Client & Fetch BG
    if user_settings.nightscout.url:
        # Check enabled flag but proceed if URL exists (warn if disabled)
        if not user_settings.nightscout.enabled:
            logger.warning("Nightscout is DISABLED in settings but URL is present. Bot will try to use it.")
            
        ns_client = NightscoutClient(
            base_url=user_settings.nightscout.url, 
            token=user_settings.nightscout.token,
            timeout_seconds=10 # More generous timeout for background job
        )
        logger.info(f"Bot connecting to NS: {user_settings.nightscout.url}")
    elif settings.nightscout.base_url:
         # Fallback to Env
         ns_client = NightscoutClient(str(settings.nightscout.base_url), settings.nightscout.token)
         logger.info("Bot connecting to NS (Env Fallback)")
    
    try:
        # Fetch BG
        if ns_client:
            try:
                sgv = await ns_client.get_latest_sgv()
                bg_val = float(sgv.sgv)
                logger.info(f"Bot obtained BG: {bg_val}")
            except Exception as e:
                logger.error(f"Bot failed to get latest SGV: {e}")
                # Don't crash, proceed with BG=None

        # 1.1 DB Fallback for Glucose (SGV)
        if bg_val is None:
            try:
                engine = get_engine()
                if engine:
                    async with AsyncSession(engine) as session:
                        from sqlalchemy import text
                        # Try fetch local SGV if entries table exists
                        # "entries" table might store SGV from background jobs
                        stmt = text("SELECT sgv, date_string FROM entries ORDER BY date_string DESC LIMIT 1") 
                        # Note: date_string is string ISO. or `date` (epoch). 
                        # Assuming entries table mirrors NS schema roughly or app schema.
                        # If "entries" doesn't exist, this throws.
                        
                        try:
                            row = (await session.execute(stmt)).fetchone()
                            if row:
                                bg_val = float(row.sgv)
                                logger.info(f"Bot obtained BG from LOCAL DB: {bg_val}")
                        except Exception:
                            # Table might not exist or be empty
                            pass
            except Exception as e:
                 logger.warning(f"DB SGV Fallback failed: {e}")
            
        # Calc IOB
        # Note: compute_iob_from_sources will use the client we passed.
        # We must keep it open.
        try:
            iob_u, _, _, _ = await compute_iob_from_sources(now_utc, user_settings, ns_client, store)
        except Exception as e:
            logger.error(f"Bot failed to calc IOB: {e}")

    except Exception as e:
        logger.error(f"Unexpected error in meal context calc: {e}")
        iob_u = 0.0
    finally:
        if ns_client:
            await ns_client.aclose()

    # 2. Calculate Bolus
    h = now_utc.hour + 1 # Approx local time fix
    slot = "lunch"
    if 5 <= h < 11: slot = "breakfast"
    elif 11 <= h < 17: slot = "lunch"
    elif 17 <= h < 23: slot = "dinner"
    else: slot = "snack"

    eff_bg = bg_val if bg_val else user_settings.targets.mid
    
    req = BolusRequestData(
        carbs_g=carbs,
        bg_mgdl=eff_bg,
        meal_slot=slot
    )
    
    
    rec = recommend_bolus(req, user_settings, iob_u)

    # 2.1 Get Injection Site (Proactive)
    injection_mgr = InjectionManager(store)
    next_site = injection_mgr.get_next_site("bolus")
    
    # 3. Message
    # If BG is unknown, we warn
    bg_str = f"{bg_val} mg/dL" if bg_val else "???"
    iob_str = f"({iob_u:.1f}u IOB)" if iob_u > 0 else ""
    
    msg_text = (
        f"🥗 **Nueva Comida Detectada** ({source})\n"
        f"Carbos: **{carbs}g**\n"
        f"Glucosa: {bg_str} {iob_str}\n\n"
        f"💉 **Sugerencia: {rec.upfront_u} U**\n"
        f"📍 **Lugar:** {next_site}\n"
        f"_Razón: {rec.explain[0]}_"
    )
    
    keyboard = [
        [
            InlineKeyboardButton(f"✅ Poner {rec.upfront_u} U", callback_data=f"bolus_confirm_{rec.upfront_u}"),
            InlineKeyboardButton("❌ Ignorar", callback_data="ignore")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await _bot_app.bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send proactive message: {e}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button clicks (Approve/Ignore)."""
    query = update.callback_query
    await query.answer() # Ack the button press
    
    data = query.data
    
    if data == "ignore":
        await query.edit_message_text(text=f"{query.message.text}\n\n❌ *Ignorado*", parse_mode="Markdown")
        logger.info("User ignored bolus suggestion.")
        return

    if data.startswith("bolus_confirm_") or data.startswith("chat_bolus_"):
        try:
            # Parse Data
            units = 0.0
            carbs = 0.0
            notes = "Bolus via Telegram Bot"
            
            if data.startswith("bolus_confirm_"):
                # Format: bolus_confirm_{units}
                val_str = data.split("_")[-1]
                units = float(val_str)
                carbs = 0 # Carbs already handled externally
            else:
                # Format: chat_bolus_{units}_{carbs}
                parts = data.split("_")
                units = float(parts[2])
                carbs = float(parts[3])
                notes = "Bolus via Chat AI"

            # Save the Bolus
            import uuid
            
            # 1. DB Session
            engine = get_engine()
            if not engine:
                 await query.edit_message_text(text="Error interno de base de datos.")
                 return

            treatment_id = str(uuid.uuid4())
            now_dt = datetime.now(timezone.utc)
            
            # Determine username (whitelist)
            # Fetch from DB (Single Tenant Assumption)
            username = "admin" 
            async with AsyncSession(engine) as session:
                from sqlalchemy import text
                stmt = text("SELECT user_id FROM user_settings LIMIT 1")
                row = (await session.execute(stmt)).fetchone()
                if row:
                    username = row.user_id
            
            success_msg = f"✅ *Tratamiento registrado*\nInsulina: {units} U"
            if carbs > 0:
                success_msg += f"\nCarbos: {carbs} g"
            
            async with AsyncSession(engine) as session:
                # Save to DB
                new_t = Treatment(
                    id=treatment_id,
                    user_id=username,
                    event_type="Meal Bolus",
                    created_at=now_dt.replace(tzinfo=None),
                    insulin=units,
                    carbs=carbs,
                    fat=0,
                    protein=0,
                    notes=notes,
                    entered_by="TelegramBot"
                )
                session.add(new_t)
                await session.commit()

                
                # Upload to NS
                settings = get_settings()
                store = DataStore(Path(settings.data.data_dir))
                user_settings = await get_bot_user_settings()
                
                if user_settings.nightscout.enabled and user_settings.nightscout.url:
                    try:
                        ns = NightscoutClient(user_settings.nightscout.url, user_settings.nightscout.token)
                        await ns.upload_treatments([{
                            "eventType": "Meal Bolus",
                            "created_at": now_dt.isoformat(),
                            "insulin": units,
                            "carbs": carbs,
                            "enteredBy": "TelegramBot",
                            "notes": notes
                        }])
                        await ns.aclose()
                        new_t.is_uploaded = True
                        await session.commit()
                        success_msg += " (subido a NS)"
                    except Exception as exc:
                        logger.error(f"NS upload failed: {exc}")
                        success_msg += " (Error NS)"
            
            # Rotate Injection Site
            try:
                settings = get_settings()
                store = DataStore(Path(settings.data.data_dir))
                im = InjectionManager(store)
                new_next = im.rotate_site("bolus")
                success_msg += f"\n\n📍 Rotado. Siguiente: {new_next}"
            except Exception as e:
                logger.error(f"Failed to rotate site: {e}")

            await query.edit_message_text(text=f"{query.message.text}\n\n{success_msg}", parse_mode="Markdown")
            
            await query.edit_message_text(text=f"{query.message.text}\n\n{success_msg}", parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Callback error: {e}")
            await query.edit_message_text(text=f"Error al registrar: {e}")


# --- Guardian Mode (Zero Cost Monitoring) ---

async def run_glucose_monitor_job() -> None:
    """
    Background Task: Checks SGV every 5 mins and alerts if Low/High.
    Uses 'check_glucose_service' logic but strictly for Telegram alerts.
    """
    global _bot_app
    if not _bot_app:
        return

    # TODO: Multi-tenant loop. For now, Single User 'admin' is the focus.
    user_id = "admin"
    chat_id = config.get_allowed_telegram_user_id()
    if not chat_id:
        return

    # 1. Get Settings & Secrets
    try:
        from app.core.db import get_engine
        engine = get_engine()
        if not engine: return
        
        async with AsyncSession(engine) as session:
            # Secrets
            ns_cfg = await svc_ns_secrets.get_ns_config(session, user_id)
            if not ns_cfg or not ns_cfg.url:
                return

            # Client
            # Low timeout for background check
            client = NightscoutClient(ns_cfg.url, ns_cfg.api_secret, timeout_seconds=5)
            
            sgv_val = 0
            direction = ""
            delta = 0.0
            date_str = ""
            
            try:
                # 2. Fetch SGV
                sgv = await client.get_latest_sgv()
                sgv_val = float(sgv.sgv)
                direction = sgv.direction or ""
                delta = sgv.delta or 0.0
                date_str = sgv.dateString
            except Exception:
                # Silent fail (connection issue)
                await client.aclose()
                return
            
            await client.aclose()
            
            # 3. Check Staleness (don't alert on old data)
            # dateString is usually ISO.
            import dateutil.parser
            try:
                reading_time = dateutil.parser.parse(date_str)
                # Ensure UTC
                if reading_time.tzinfo is None:
                    reading_time = reading_time.replace(tzinfo=timezone.utc)
                
                now = datetime.now(timezone.utc)
                age_min = (now - reading_time).total_seconds() / 60
                
                if age_min > 20:
                    # Data is too old (>20 mins), don't alert (sensor might be warming up/dead)
                    return
            except Exception:
                pass

            # 4. Threshold Logic
            # Hardcoded Safeties or Fetch from UserSettings
            # We'll use "Safe" defaults: <70 and >250
            # Ideally fetch from UserSettings.targets
            
            LOW_THRESH = 70
            HIGH_THRESH = 260 
            
            alert_type = None
            msg = ""
            
            if sgv_val <= LOW_THRESH:
                alert_type = "low"
                msg = f"🚨 **ALERTA BAJA: {int(sgv_val)}** {direction}\n📉 Delta: {delta:+.1f}"
            elif sgv_val >= HIGH_THRESH:
                alert_type = "high"
                msg = f"⚠️ **ALERTA ALTA: {int(sgv_val)}** {direction}\n📈 Delta: {delta:+.1f}"
            
            if not alert_type:
                # Normal range, clear any active state if needed?
                # Actually, we rely on 'Snooze' for alerts.
                return
                
            # 5. Anti-Spam (Snooze) Logic
            # We don't want to alert every 5 mins.
            # Low: Alert every 15 mins?
            # High: Alert every 60 mins?
            
            # Use UserNotificationState to store 'last_alert_time'
            from app.models.notifications import UserNotificationState
            from sqlalchemy import select
            
            key = f"guardian_{alert_type}"
            stmt = select(UserNotificationState).where(
                UserNotificationState.user_id == user_id,
                UserNotificationState.key == key
            )
            state_row = (await session.execute(stmt)).scalars().first()
            
            should_send = True
            now_utc = datetime.now(timezone.utc)
            
            if state_row:
                last_sent = state_row.seen_at # Reuse 'seen_at' as 'sent_at'
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
                
                elapsed_min = (now_utc - last_sent).total_seconds() / 60
                
                snooze_time = 20 if alert_type == "low" else 60 # 20m for low, 1h for high
                
                if elapsed_min < snooze_time:
                    should_send = False
            
            if should_send:
                # Send Message
                try:
                    await _bot_app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                    
                    # Update State
                    if state_row:
                        state_row.seen_at = now_utc
                    else:
                        new_state = UserNotificationState(
                            user_id=user_id,
                            key=key,
                            seen_at=now_utc
                        )
                        session.add(new_state)
                    await session.commit()
                    logger.info(f"Guardian Mode sent alert: {alert_type} ({sgv_val})")
                except Exception as e:
                    logger.error(f"Failed to send Guardian Alert: {e}")

    except Exception as e:
        logger.error(f"Guardian Job Error: {e}")

