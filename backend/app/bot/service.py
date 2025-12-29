import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram import constants

from app.core import config
from app.bot import ai

# Sidecar dependencies
from pathlib import Path
from datetime import datetime, timezone
from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.services.bolus import recommend_bolus, BolusRequestData
from app.services.injection_sites import InjectionManager

# DB Access for Settings
from app.core.db import get_engine, AsyncSession
from app.services import settings_service as svc_settings
from app.models.settings import UserSettings

logger = logging.getLogger(__name__)

# Global Application instance
_bot_app: Optional[Application] = None

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
            # Assume 'admin' or get first user? 'admin' is safe default seed.
            res = await svc_settings.get_user_settings_service("admin", session)
            if res and res.get("settings"):
                try:
                    return UserSettings.model_validate(res["settings"])
                except Exception as e:
                    logger.error(f"Failed to validate DB settings: {e}")
    
    # Fallback to JSON Store
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
        ns_client = None
        if user_settings.nightscout.enabled and user_settings.nightscout.url:
            ns_client = NightscoutClient(
                base_url=user_settings.nightscout.url,
                token=user_settings.nightscout.token,
                timeout_seconds=5
            )
            try:
                sgv = await ns_client.get_latest_sgv()
                arrow = sgv.direction or ""
                delta = f"{sgv.delta:+.1f}" if sgv.delta is not None else "?"
                context_lines.append(f"GLUCOSA: {sgv.sgv} {user_settings.nightscout.units} ({arrow}) Delta: {delta}")
            except Exception as e:
                context_lines.append(f"GLUCOSA: Error leyendo ({str(e)})")

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
        h = now_utc.hour + 2 # CET roughly? Or just list all? List all is safer.
        
        context_lines.append("\nCONF USUARIO:")
        context_lines.append(f"- ISF (Sensibilidad): {user_settings.cf.breakfast} (D) / {user_settings.cf.lunch} (A) / {user_settings.cf.dinner} (C)")
        context_lines.append(f"- CR (Ratio): {user_settings.cr.breakfast} (D) / {user_settings.cr.lunch} (A) / {user_settings.cr.dinner} (C)")
        context_lines.append(f"- Objetivo: {user_settings.targets.mid} mg/dL")

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
            
    except Exception as e:
        logger.warning(f"Bot failed to fetch detailed context: {e}")
        context_lines.append(f"ERROR LECTURA DATOS: {e}")

    context_str = "\n".join(context_lines)

    response = await ai.chat_completion(text, context=context_str, mode=mode)
    await update.message.reply_text(response)

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

    if data.startswith("bolus_confirm_"):
        try:
            val_str = data.split("_")[-1]
            units = float(val_str)
            
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
            # We assume single user mode for this bot: provided by current config
            # But the Treatment model requires a username.
            # We can fetch it from settings or just use "admin" or the telegram user mapping.
            # For simplicity, we query settings owner or default "admin".
            username = "admin" # Default fallabck
            
            async with AsyncSession(engine) as session:
                 # Try to get username from settings owner? 
                 # Or just use the one in DB.
                 # Let's assume 'admin' for now or 'user'. 
                 # Ideally we should match the Telegram User ID to a User in DB.
                 pass
            
            # We can just save with username='admin' if valid
            
            success_msg = f"✅ *Bolo de {units} U registrado*"
            
            async with AsyncSession(engine) as session:
                # Save to DB
                new_t = Treatment(
                    id=treatment_id,
                    user_id=username, # TODO: dynamic
                    event_type="Meal Bolus",
                    created_at=now_dt.replace(tzinfo=None),
                    insulin=units,
                    carbs=0, # Carbs were logged by the meal entry previously
                    fat=0,
                    protein=0,
                    notes="Bolus via Telegram Bot",
                    entered_by="TelegramBot",
                    is_uploaded=False
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
                            "carbs": 0, # Carbs separate
                            "enteredBy": "TelegramBot",
                            "notes": "Via Bot"
                        }])
                        await ns.aclose()
                        new_t.is_uploaded = True
                        await session.commit()
                        success_msg += " (y subido a Nightscout)"
                    except Exception as exc:
                        logger.error(f"NS upload failed: {exc}")
                        success_msg += " (Guardado Local, error NS)"
            
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
            
        except Exception as e:
            logger.error(f"Callback error: {e}")
            await query.edit_message_text(text=f"Error al registrar: {e}")

