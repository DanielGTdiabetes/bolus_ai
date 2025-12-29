import logging
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram import constants

from app.core import config
from app.bot import ai

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

    response = await ai.chat_completion(text, mode=mode)
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
