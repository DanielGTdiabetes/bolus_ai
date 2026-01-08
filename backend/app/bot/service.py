import logging
import asyncio
import os
import tempfile
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse, urlunparse
import uuid


from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram import constants

from app.core import config
from app.bot import ai
from app.bot import tools
from app.bot import voice
from app.bot.state import health, BotMode
from app.bot import proactive
from app.bot import context_builder
from app.bot.llm import router
from app.bot.image_renderer import generate_injection_image
from app.bot.context_vars import bot_user_context

# Sidecar dependencies
from pathlib import Path
from datetime import datetime, timezone, timedelta
from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.services.dexcom_client import DexcomClient
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.services.bolus_engine import calculate_bolus_v2
from app.services.basal_repo import get_latest_basal_dose
from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2, GlucoseUsed
from app.bot.capabilities.registry import build_registry, Permission


SNAPSHOT_STORAGE: Dict[str, Any] = {}





# DB Access for Settings
from app.core.db import SessionLocal
from app.services import settings_service as svc_settings
from app.services import nightscout_secrets_service as svc_ns_secrets
from app.models.settings import UserSettings
from app.bot.user_settings_resolver import resolve_bot_user_settings

async def fetch_history_context(user_settings: UserSettings, hours: int = 6) -> str:
    """Fetches simplified glucose history context using Local DB as primary, Nightscout as fallback."""
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=hours)
    
    entries = []
    source = "Bolus AI"

    # 1. Try Local DB
    try:
        async with SessionLocal() as session:
            from sqlalchemy import text
            # We need sgv and date. date in internal DB is usually ISO string or epoch.
            # In entries table it's typically date_string (ISO) or date (epoch ms common in NS sync)
            stmt = text("""
                SELECT sgv, date 
                FROM entries 
                WHERE date >= :start_ms 
                ORDER BY date ASC
            """)
            # NS epoch is ms
            start_ms = int(start_time.timestamp() * 1000)
            res = await session.execute(stmt, {"start_ms": start_ms})
            for row in res.fetchall():
                # mock a NS-like object for compatibility with logic below
                from dataclasses import dataclass
                @dataclass
                class MockEntry:
                    sgv: float
                    date: int
                entries.append(MockEntry(sgv=float(row[0]), date=int(row[1])))
    except Exception as e:
        logger.warning(f"Local history fetch failed: {e}")

    # 2. Fallback to Nightscout if DB empty or failed
    if not entries and user_settings.nightscout.url:
        source = "Nightscout"
        client = None
        try:
            client = NightscoutClient(
                base_url=user_settings.nightscout.url,
                token=user_settings.nightscout.token,
                timeout_seconds=10
            )
            count = int(hours * 12 * 1.5) 
            entries = await client.get_sgv_range(start_dt=start_time, end_dt=now, count=count)
        except Exception as e:
            logger.warning(f"NS history fallback failed: {e}")
        finally:
            if client: await client.aclose()

    if not entries:
        return f"HISTORIAL ({hours}h): No hay datos disponibles."

    # Compute Stats
    values = [e.sgv for e in entries if e.sgv is not None]
    if not values: 
        return f"HISTORIAL ({hours}h): Datos vacíos."

    avg = sum(values) / len(values)
    min_v = min(values)
    max_v = max(values)
    in_range = sum(1 for v in values if 70 <= v <= 180)
    tir_pct = (in_range / len(values)) * 100
    
    # Sample Trend (Every ~30 mins)
    sorted_entries = sorted(entries, key=lambda x: x.date)
    step = max(1, len(sorted_entries) // (hours * 2)) 
    graph_points = [str(int(sorted_entries[i].sgv)) for i in range(0, len(sorted_entries), step)]
    
    if len(graph_points) > 20:
         step2 = len(graph_points) // 20 + 1
         graph_points = graph_points[::step2]
         
    graph_str = " -> ".join(graph_points)
    
    return (
        f"RESUMEN HISTORIAL ({hours}h - Fuente: {source}):\n"
        f"- Promedio: {int(avg)} mg/dL\n"
        f"- TIR (70-180): {int(tir_pct)}%\n"
        f"- Rango: {int(min_v)} - {int(max_v)}\n"
        f"- Evolución: {graph_str}"
    )



logger = logging.getLogger(__name__)

# Global Application instance
_bot_app: Optional[Application] = None
_polling_task: Optional[asyncio.Task] = None


async def bot_send(
    chat_id: int,
    text: str,
    *,
    bot=None,
    log_context: str = "reply",
    **kwargs: Any,
) -> Optional[Any]:
    """Centralized sender for Telegram replies with health tracking."""
    logger.info("sending reply", extra={"chat_id": chat_id, "context": log_context})

    target_bot = bot or (_bot_app.bot if _bot_app else None)
    if not target_bot:
        error_msg = "bot_unavailable"
        logger.error(f"reply failed: {error_msg}")
        health.set_reply_error(error_msg)
        return None

    try:
        result = await target_bot.send_message(chat_id=chat_id, text=text, **kwargs)
        health.mark_reply_success()
        logger.info("reply ok", extra={"chat_id": chat_id, "context": log_context})
        return result
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error(f"reply failed: {error_msg}")
        health.set_reply_error(error_msg)
        return None


async def edit_message_text_safe(editor, *args: Any, **kwargs: Any) -> Optional[Any]:
    try:
        return await editor.edit_message_text(*args, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            logger.info("edit_message_not_modified", extra={"context": kwargs.get("context")})
            return None
        raise


async def reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs: Any) -> Optional[Any]:
    """Convenience wrapper for message replies."""
    return await bot_send(
        chat_id=update.effective_chat.id,
        text=text,
        bot=context.bot,
        log_context="reply_text",
        **kwargs,
    )


def decide_bot_mode() -> Tuple[BotMode, str]:
    """
    Decide how the bot should run based on environment.
    Returns (mode, reason)
    """
    if not config.is_telegram_bot_enabled():
        return BotMode.DISABLED, "feature_flag_off"

    token = config.get_telegram_bot_token()
    if not token:
        return BotMode.DISABLED, "missing_token"

    public_url = config.get_public_bot_url()
    if public_url:
        return BotMode.WEBHOOK, "public_url_present"

    return BotMode.POLLING, "missing_public_url"


def build_expected_webhook() -> Tuple[Optional[str], str]:
    """
    Returns (expected_url, source_env_key)
    """
    public_url, source = config.get_public_bot_url_with_source()
    if not public_url:
        return None, source
    return f"{public_url}/api/webhook/telegram", source

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    error_id = uuid.uuid4().hex[:8]
    
    # Log full traceback
    logger.exception(f"Exception while handling an update (error_id={error_id}): {context.error}", exc_info=context.error)
    
    # Register in health state
    health.set_error(str(context.error), error_id=error_id, exc=context.error)
    
    # User feedback
    if update and isinstance(update, Update) and update.effective_message:
        try:
             await reply_text(update, context, f"⚠️ Error interno del bot (id: {error_id}).")
        except Exception as e:
             logger.error(f"Failed to send error reply: {e}")

async def _check_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if user is authorized."""
    allowed_id = config.get_allowed_telegram_user_id()
    if not allowed_id:
        # If no ID set, maybe allow all? Better safe than sorry: Allow NONE or Log warning
        # For this personal assistant, strict allow list is best.
        logger.error("ALLOWED_TELEGRAM_USER_ID is not configured. Bot will reject all requests.")
        if update and getattr(update, "message", None):
            await reply_text(
                update,
                context,
                "⚠️ Bot sin configurar: falta ALLOWED_TELEGRAM_USER_ID. "
                "Configura el ID autorizado para habilitar respuestas."
            )
        return False
        
    user_id = update.effective_user.id
    if user_id != allowed_id:
        logger.warning(f"Unauthorized access attempt from ID: {user_id}")
        await reply_text(update, context, "⛔ Acceso denegado. Este bot es privado.")
        return False
    return True

async def get_bot_user_settings(username: Optional[str] = None) -> UserSettings:
    """
    Helper to fetch settings from the best available user.
    Defaults to resolver priority (preferred -> BOT_DEFAULT_USERNAME -> freshest non-default).
    """
    resolved_settings, resolved_user = await resolve_bot_user_settings(username)
    logger.info("Bot using settings for user_id='%s'", resolved_user)
    return resolved_settings

def get_current_meal_slot(settings: UserSettings) -> str:
    """Infers current meal slot based on User Schedule (Local Time)."""
    from datetime import datetime
    from app.utils.timezone import to_local
    
    # Use user local time (default Europe/Madrid)
    now_local = to_local(datetime.now(timezone.utc))
    h = now_local.hour
    sch = settings.schedule
    
    if sch.breakfast_start_hour <= h < sch.lunch_start_hour:
        return "breakfast"
    elif sch.lunch_start_hour <= h < sch.dinner_start_hour:
        return "lunch"
    elif h >= sch.dinner_start_hour or h < sch.breakfast_start_hour:
        return "dinner"
    
    # Default fallback
    return "snack"

def _is_admin(user_id: int) -> bool:
    allowed = config.get_allowed_telegram_user_id()
    return allowed is not None and user_id == allowed

async def _exec_tool(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str, args: dict) -> None:
    registry = build_registry()
    tool = next((t for t in registry.tools if t.name == name), None)
    
    if not tool:
        await reply_text(update, context, f"❌ Tool no encontrada: {name}")
        return

    # Permission Check
    user_id = update.effective_user.id
    if tool.permission == Permission.admin_only and not _is_admin(user_id):
         await reply_text(update, context, "⛔ Requiere permisos de Admin.")
         health.record_action(f"tool:{name}", False, "permission_denied")
         return
    
    # Set Context for Tool Execution
    username = update.effective_user.username if update.effective_user else "unknown"
    token = bot_user_context.set(username)
    
    try:
        if name == "calculate_bolus":
            # Special wrapper for interactive bolus
            await _handle_add_treatment_tool(update, context, {"carbs": args.get("carbs"), "notes": "Command", "insulin": None})
            health.record_action(f"tool:{name}", True)
            return

        res = tool.fn(**args)
        if hasattr(res, "__await__"):
            res = await res
            
        # Format output
        text = f"🔧 **{name}**\nResult: `{res}`"
        # Special formatting for some tools
        if name == "get_status_context":
             text = f"📉 BG: {res.bg_mgdl} {res.direction or ''} Δ {res.delta}\nIOB: {res.iob_u} | COB: {res.cob_g}\nQuality: {res.quality}"
        elif name == "simulate_whatif":
             text = f"🔮 **Simulación**\n{res.summary}"
        elif name == "calculate_correction":
             text = f"💉 **Corrección**\n{res.units} U\n" + "\n".join(res.explanation)
        elif name == "get_nightscout_stats":
             text = f"📊 **Stats ({args.get('range_hours')}h)**\nAvg: {res.avg_bg} | TIR: {res.tir_pct}%"
        elif name in ["get_injection_site", "get_last_injection_site"]:
             label = "Zona Recomendada" if name == "get_injection_site" else "Última Zona Usada"
             text = f"📍 **{label}:** {res.name} {res.emoji}"
             # Send Image if available
             if res.image:
                 try:
                     # Use site_id if available to generate dynamic image
                     target_id = getattr(res, "id", None)
                     if target_id:
                         assets = Path(get_settings().data.static_dir or "app/static") / "assets"
                         # Fix path if needed (Docker/Local discrepancy)
                         if not assets.exists():
                             assets = Path(os.getcwd()) / "app" / "static" / "assets"
                         
                         img_bytes = generate_injection_image(target_id, assets)
                         if img_bytes:
                             await context.bot.send_photo(chat_id=update.effective_chat.id, photo=img_bytes)
                 except Exception as img_err:
                     logger.error(f"Failed to send injection image ({res.image}): {img_err}", exc_info=True)

        await reply_text(update, context, text)
        health.record_action(f"tool:{name}", True)
        
    except Exception as e:
        logger.error(f"Tool exec error: {e}")
        await reply_text(update, context, f"💥 Error ejecutando {name}: {e}")
        health.record_action(f"tool:{name}", False, str(e))
    finally:
        bot_user_context.reset(token)

async def _exec_job(update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: str) -> None:
    registry = build_registry()
    job = next((j for j in registry.jobs if j.id == job_id), None)
    
    if not job:
         await reply_text(update, context, f"❌ Job no encontrado: {job_id}")
         return

    if not _is_admin(update.effective_user.id):
         await reply_text(update, context, "⛔ Solo admin.")
         return
         
    if not job.run_now_fn:
         await reply_text(update, context, f"⚠️ El job {job_id} no es ejecutable manualmente.")
         return

    await reply_text(update, context, f"⏳ Ejecutando job: {job_id}...")
    try:
        res = job.run_now_fn()
        if hasattr(res, "__await__"):
            await res
        await reply_text(update, context, f"✅ Job {job_id} completado.")
        health.record_action(f"job:{job_id}", True)
    except Exception as e:
        logger.error(f"Job exec error: {e}")
        await reply_text(update, context, f"💥 Error job {job_id}: {e}")
        health.record_action(f"job:{job_id}", False, str(e))

# --- Operational Commands ---

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status: Minimal context."""
    if not await _check_auth(update, context): return
    await _exec_tool(update, context, "get_status_context", {})

async def capabilities_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/capabilities: List top tools/jobs."""
    if not await _check_auth(update, context): return
    reg = build_registry()
    msg = "semáforo de capacidades:\n\n**Tools:**\n"
    for t in reg.tools[:5]:
        msg += f"- /{t.name}: {t.description[:40]}...\n"
    msg += "\n**Jobs:**\n"
    for j in reg.jobs[:5]:
        msg += f"- {j.id}: {j.description[:40]}...\n"
    msg += "\nUsa /tools o /jobs para ver todo."
    await reply_text(update, context, msg)

async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tools: Full list."""
    if not await _check_auth(update, context): return
    reg = build_registry()
    msg = "🛠️ **Herramientas Disponibles**\n"
    for t in reg.tools:
        args = ", ".join(t.input_schema.get("properties", {}).keys())
        msg += f"/{t.name} [{args}]\n  _{t.description}_\n"
    await reply_text(update, context, msg)

async def jobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/jobs: Full list + state."""
    if not await _check_auth(update, context): return
    reg = build_registry()
    msg = "⚙️ **Jobs del Sistema**\n"
    for j in reg.jobs:
        next_run = j.next_run_fn() if j.next_run_fn else "?"
        last_st = j.last_run_state_fn() if j.last_run_state_fn else None
        
        status = "⚪ (PENDING)"
        if last_st and last_st.get("last_run_at"):
            if last_st.get("last_run_ok"):
                status = "🟢 (OK)"
            else:
                status = "🔴 (ERR)"
            
        msg += f"{status} **{j.id}**\n  Next: {next_run}\n"
        if last_st and last_st.get("last_run_at"):
             iso = last_st.get('last_run_at')
             msg += f"  Last: {iso} ({'OK' if last_st.get('last_run_ok') else 'ERR'})\n"
    await reply_text(update, context, msg)


async def run_job_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/run <job_id>: Manually trigger job."""
    if not await _check_auth(update, context): return
    if not context.args:
        await reply_text(update, context, "Uso: /run <job_id>")
        return
    job_id = context.args[0]
    await _exec_job(update, context, job_id)

# --- Tool Wrappers ---

async def tool_wrapper_bolo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/bolo <carbs>"""
    if not await _check_auth(update, context): return
    if not context.args:
        await reply_text(update, context, "Uso: /bolo <carbs_g>")
        return
    try:
        carbs = float(context.args[0])
        await _exec_tool(update, context, "calculate_bolus", {"carbs": carbs})
    except ValueError:
        await reply_text(update, context, "Error: carbs debe ser número.")

async def tool_wrapper_corrige(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/corrige [target]"""
    if not await _check_auth(update, context): return
    target = None
    if context.args:
        try:
            target = float(context.args[0])
        except ValueError:
            await reply_text(update, context, "Error: target debe ser número (opcional).")
            return
    await _exec_tool(update, context, "calculate_correction", {"target_bg": target})

async def tool_wrapper_whatif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/whatif <carbs>"""
    if not await _check_auth(update, context): return
    if not context.args:
        await reply_text(update, context, "Uso: /whatif <carbs>")
        return
    try:
        carbs = float(context.args[0])
        await _exec_tool(update, context, "simulate_whatif", {"carbs": carbs})
    except ValueError:
        await reply_text(update, context, "Error: carbs debe ser número.")

async def tool_wrapper_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats [hours]"""
    if not await _check_auth(update, context): return
    hours = 24
    if context.args:
        try:
            hours = int(context.args[0])
        except ValueError: pass
    await _exec_tool(update, context, "get_nightscout_stats", {"range_hours": hours})



async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lightweight liveness probe that bypasses AI and Nightscout."""
    if not await _check_auth(update, context):
        return
    await reply_text(update, context, "pong")



async def _process_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Wrapper to inject user context."""
    if not text: return
    
    # Set Context
    username = update.effective_user.username if update.effective_user else "unknown"
    token = bot_user_context.set(username)
    try:
        await _process_text_input_internal(update, context, text)
    finally:
        bot_user_context.reset(token)

async def _process_text_input_internal(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Shared logic for text and transcribed voice (Internal)."""
    
    # Check Master Switch
    try:
        user_settings = await get_bot_user_settings()
        if not user_settings.bot.enabled:
             # Allow commands to potentially proceed if they start with / (except if we want total silence/block)
             if text.startswith("/"):
                 pass 
             else:
                 await reply_text(update, context, "😴 Bot desactivado desde la App.")
                 return
    except Exception as e:
        logger.error(f"Failed to check bot status: {e}")

    cmd = text.lower().strip()

    if cmd == "ping":
        await reply_text(update, context, "pong")
        return

    # 0. Intercept Pending Inputs (Manual Bolus Edit)
    pending_bolus_req = context.user_data.get("editing_bolus_request")
    if pending_bolus_req:
        try:
            val = float(text.replace(",", "."))
            del context.user_data["editing_bolus_request"]
            
            # Confirm Card
            keyboard = [
                [
                    InlineKeyboardButton(f"✅ Confirmar {val} U", callback_data=f"accept_manual|{val}|{pending_bolus_req}"),
                    InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel|{pending_bolus_req}")
                ]
            ]
            await reply_text(
                update, 
                context, 
                f"¿Confirmas el cambio a **{val} U**?", 
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return
        except ValueError:
            await reply_text(update, context, "⚠️ Por favor, introduce un número válido.")
            return

    # 0. Intercept Pending Inputs (Combo Followup)
    pending_combo_tid = context.user_data.get("pending_combo_tid")
    if pending_combo_tid:
        try:
            units = float(text.replace(",", "."))
            # Clear pending
            del context.user_data["pending_combo_tid"]
            
            # Ask Confirm
            keyboard = [
                [
                    InlineKeyboardButton(f"✅ Registrar {units} U", callback_data=f"combo_confirm|{units}|{pending_combo_tid}"),
                    InlineKeyboardButton("❌ Cancelar", callback_data=f"combo_no|{pending_combo_tid}")
                ]
            ]
            await reply_text(update, context, f"¿Registrar **{units} U** para la 2ª parte del bolo?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return
        except ValueError:
             await reply_text(update, context, "⚠️ Por favor, introduce un número válido (ej. 2.5).")
             return

    # 0. Intercept Rename Treatment
    renaming_id = context.user_data.get("renaming_treatment_id")
    if renaming_id:
        new_note = text
        del context.user_data["renaming_treatment_id"]
        
        # Logic to update
        try:
             # Update Local
             settings = get_settings()
             store = DataStore(Path(settings.data.data_dir))
             events = store.load_events()
             found = False
             for e in events:
                 if e.get("id") == renaming_id or e.get("_id") == renaming_id:
                     e["notes"] = new_note
                     # Also update items if possible? MealEntry? 
                     # For now just notes.
                     found = True
             if found: store.save_events(events)

             # Update DB
             async with SessionLocal() as session:
                  from app.models.treatment import Treatment
                  from sqlalchemy import update as sql_update
                  stmt = sql_update(Treatment).where(Treatment.id == renaming_id).values(notes=new_note)
                  await session.execute(stmt)
                  await session.commit()
             
             await reply_text(update, context, f"✅ Nota actualizada: {new_note}")
        except Exception as e:
             logger.error(f"Rename failed: {e}")
             await reply_text(update, context, "❌ Error actualizando nota.")
        return

    # 0. Intercept Save Favorite
    fav_tid = context.user_data.get("saving_favorite_tid")
    if fav_tid:
        fav_name = text
        del context.user_data["saving_favorite_tid"]
        
        try:
            # Fetch treatment to get macros
            settings = get_settings()
            store = DataStore(Path(settings.data.data_dir))
            events = store.load_events()
            txn = next((e for e in events if e.get("id") == fav_tid or e.get("_id") == fav_tid), None)
            
            if txn:
                carbs = txn.get("carbs", 0)
                fat = txn.get("fat", 0)
                protein = txn.get("protein", 0)
                
                # Call tool save_favorite logic directly
                res = await tools.save_favorite_food({
                    "name": fav_name,
                    "carbs": carbs,
                    "fat": fat,
                    "protein": protein,
                    "notes": "Desde Historial"
                })
                if res.ok:
                    await reply_text(update, context, f"⭐ Guardado plato: **{fav_name}** ({carbs}g HC)")
                else:
                    await reply_text(update, context, f"❌ Error guardando: {res.error}")
            else:
                 await reply_text(update, context, "⚠️ No encuentro el tratamiento original.")
        except Exception as e:
            logger.error(f"Fav save failed: {e}")
            await reply_text(update, context, "❌ Error procesando favorito.")
        return

    # 0. Intercept Draft Edit
    editing_draft_id = context.user_data.get("editing_draft_id")
    if editing_draft_id:
        try:
            new_carbs = float(text.replace(",", "."))
            del context.user_data["editing_draft_id"]
            
            # Update Draft in DB
            from app.services.nutrition_draft_service import NutritionDraftService
            try:
                username = update.effective_user.username or "admin"
                async with SessionLocal() as session:
                    # We need a method to overwrite carbs.
                    # update_draft is additive. We need a "set" method or just overwrite manually.
                    # Let's do manual overwrite for simplicity here.
                    from app.models.draft_db import NutritionDraftDB
                    from sqlalchemy import select, update as sql_update
                    
                    # Update
                    stmt = (
                        sql_update(NutritionDraftDB)
                        .where(NutritionDraftDB.id == editing_draft_id)
                        .values(carbs=new_carbs, updated_at=datetime.now(timezone.utc))
                    )
                    await session.execute(stmt)
                    await session.commit()
                    
                    # Fetch updated
                    stmt_get = select(NutritionDraftDB).where(NutritionDraftDB.id == editing_draft_id)
                    res = await session.execute(stmt_get)
                    updated_db = res.scalars().first()
                    
                    if updated_db:
                         # Notify again (Refresh view)
                         draft_obj = await NutritionDraftService.get_draft(username, session) # Helper
                         # Actually get_draft might return None if expired, but we just updated it.
                         # Let's convert manually or re-fetch properly.
                         # Just triggering on_draft_updated is easiest.
                         from app.models.draft import NutritionDraft
                         d_pydantic = NutritionDraft(
                            id=updated_db.id,
                            user_id=updated_db.user_id,
                            carbs=updated_db.carbs,
                            fat=updated_db.fat,
                            protein=updated_db.protein,
                            fiber=updated_db.fiber,
                            created_at=updated_db.created_at,
                            updated_at=updated_db.updated_at,
                            expires_at=updated_db.expires_at,
                            status=updated_db.status,
                            last_hash=updated_db.last_hash
                         )
                         await on_draft_updated(username, d_pydantic, "updated_replace")
                    
            except Exception as e:
                logger.error(f"Failed to update draft DB: {e}")
                await reply_text(update, context, "❌ Error al actualizar borrador.")
                
            return
        except ValueError:
             await reply_text(update, context, "⚠️ Por favor, introduce un número válido para los hidratos.")
             # Keep state
             return

    if cmd in ["status", "estado"]:
        res = await tools.execute_tool("get_status_context", {})
        if isinstance(res, tools.ToolError):
            await reply_text(update, context, f"⚠️ {res.message}")
        else:
            await reply_text(
                update,
                context,
                f"📉 BG: {res.bg_mgdl} {res.direction or ''} Δ {res.delta} | IOB {res.iob_u} | COB {res.cob_g} | {res.quality}"
            )
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
            async with SessionLocal() as session:
                # List all users
                from sqlalchemy import text as sql_text
                stmt = sql_text("SELECT user_id, settings FROM user_settings")
                rows = (await session.execute(stmt)).fetchall()
                out.append(f"📊 **Usuarios en DB:** {len(rows)}")
                for r in rows:
                    uid = r.user_id
                    raw = r.settings
                    ns_raw = raw.get("nightscout", {})
                    url_raw = ns_raw.get("url", "EMPTY")
                    out.append(f"- User `{uid}`: NS_URL=`{url_raw}`")

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
            async with SessionLocal() as session:
                from sqlalchemy import text as sql_text
                stmt = sql_text("SELECT created_at, insulin FROM treatments ORDER BY created_at DESC LIMIT 1")
                row = (await session.execute(stmt)).fetchone() 
                if row:
                     out.append(f"💉 **Último Bolo (DB):** {row.insulin} U ({row.created_at.strftime('%H:%M')})")
                else:
                     out.append(f"💉 **Último Bolo (DB):** (Vacío)")

        except Exception as e:
            out.append(f"💥 **Error Script:** `{e}`")
            
        # Send without markdown to avoid parsing errors (underscores in URLs, etc.)
        await reply_text(update, context, "\n".join(out))
        return

    # --- AI Layer ---
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
    
    logger.info(f"[LLM] entering router chat_id={update.effective_chat.id} user={update.effective_user.username}")
    t0 = datetime.now()
    
    # 1. Build Context
    ctx = await context_builder.build_context(update.effective_user.username, update.effective_chat.id)
    t1 = datetime.now()
    ctx_ms = (t1 - t0).total_seconds() * 1000

    # 2. Router
    try:
        bot_reply = await router.handle_text(update.effective_user.username, update.effective_chat.id, text, ctx)
        logger.info(f"[LLM] router ok chat_id={update.effective_chat.id}")
    except Exception as e:
        # Emergency catch for router layer itself
        err_id = uuid.uuid4().hex[:8]
        logger.exception(f"[LLM] router CRIT (id={err_id})", exc_info=e)
        health.set_error(f"Router Exception: {e}", error_id=err_id, exc=e)
        await reply_text(update, context, f"⚠️ Error IA ({err_id}).")
        return

    t2 = datetime.now()
    llm_ms = (t2 - t1).total_seconds() * 1000
    
    # 3. Handle Pending Actions (Buttons)
    if bot_reply.pending_action:
        p = bot_reply.pending_action
        p["timestamp"] = datetime.now().timestamp()
        SNAPSHOT_STORAGE[p["id"]] = p
        
    # 4. Send Reply
    if bot_reply.buttons:
        reply_markup = InlineKeyboardMarkup(bot_reply.buttons)
        await reply_text(update, context, bot_reply.text, reply_markup=reply_markup)
    else:
        await reply_text(update, context, bot_reply.text)

    # 5. Send Image if present (Injection Site)
    if bot_reply.site_id:
        try:
             assets = Path(get_settings().data.static_dir or "app/static") / "assets"
             if not assets.exists():
                 assets = Path(os.getcwd()) / "app" / "static" / "assets"
             
             img_bytes = generate_injection_image(bot_reply.site_id, assets)
             if img_bytes:
                 await context.bot.send_photo(chat_id=update.effective_chat.id, photo=img_bytes)
        except Exception as e:
             logger.error(f"Failed to send bot reply image: {e}")


    # 5. Observability
    logger.info(f"AI Req: ctx={int(ctx_ms)}ms llm={int(llm_ms)}ms")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Standard /start command."""
    if not await _check_auth(update, context): return
    
    user = update.effective_user
    mode = health.mode.value if health else "unknown"
    allowed = config.get_allowed_telegram_user_id()
    whitelist_msg = "⚠️ ALLOWED_TELEGRAM_USER_ID falta: el bot responderá solo a /start" if not allowed else f"Usuario permitido: {allowed}"
    await reply_text(
        update,
        context,
        f"Hola {user.first_name}! Soy tu asistente de diabetes (Bolus AI).\n"
        f"Modo bot: {mode}.\n"
        f"{whitelist_msg}\n"
        "Puedes pedirme: calcular bolo, corrección, simulación what-if, ver estado o stats. "
        "Envía texto libre o nota de voz."
    )



async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Text Handler - The Python Router."""
    if not await _check_auth(update, context): return
    
    text = update.message.text
    await _process_text_input(update, context, text)

# --- AI Tools Definition ---
AI_TOOLS = [
    {
        "function_declarations": tools.AI_TOOL_DECLARATIONS
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
    
    await reply_text(update, context, "⚙️ Procesando solicitud de tratamiento...")
    
    # 1. Fetch Context
    settings = get_settings()
    store = DataStore(Path(settings.data.data_dir))
    user_settings = await get_bot_user_settings()
    
    bg_val = None
    iob_u = 0.0
    iob_info = None
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
                async with SessionLocal() as session:
                    from sqlalchemy import text
                    stmt = text("SELECT sgv FROM entries ORDER BY date_string DESC LIMIT 1") 
                    row = (await session.execute(stmt)).fetchone()
                    if row: bg_val = float(row.sgv)
            except Exception: pass

        # Calc IOB
        now_utc = datetime.now(timezone.utc)
        try:
            iob_u, _, iob_info, _ = await compute_iob_from_sources(now_utc, user_settings, ns_client, store)
        except Exception:
            iob_u = None
            iob_info = None
        
    finally:
        if ns_client: await ns_client.aclose()
        
    # 2. Recommendation Logic (V2 Engine)
    # ---------------------------------------------------------
    # Generate Request ID
    request_id = str(uuid.uuid4())[:8] # Short 8-char ID for UX
    
    # Resolve Parameters
    slot = get_current_meal_slot(user_settings)
    
    # Calculate IOB & Context
    eff_bg = bg_val if bg_val else user_settings.targets.mid
    
    # Create Request V2
    req_v2 = BolusRequestV2(
        carbs_g=carbs,
        target_mgdl=user_settings.targets.mid, # Default
        meal_slot=slot,
        fat_g=0, # Bot doesn't support macros yet in this tool
        protein_g=0,
        bg_mgdl=bg_val,
        # If user asked for specific insulin, we still calculate standard
        # but we might override later? No, tool says 'calculate'.
        # If user provided 'insulin' arg, usually it means 'log this'.
        # But this tool is _handle_add_treatment which implies calculation if insulin is None.
    )

    # Manual Insulin Override?
    if insulin_req is not None:
         # If user GAVE insulin amount, we treat it as a direct log request?
         # Or we show it as "Requested".
         # For consistency with "Snapshot", we should simulate a calculation 
         # that results in this amount? Or just bypass calculation?
         # The requirement says: "Bot calls function... receives object... The button uses THAT snapshot"
         # If user explicitly said "Add 5U", maybe we shouldn't fail validation.
         # But the logic below was calculating if insulin=None.
         pass

    # Autosens (Default OFF for bot unless specified? Let's assume OFF to match Web default or User Settings)
    # We just pass 1.0/None for now or fetch.
    # To be safe/fast: 1.0
    
    glucose_info = GlucoseUsed(
        mgdl=bg_val,
        source="nightscout" if ns_client else "manual",
        trend=None, # Todo: fetch trend
        is_stale=False
    )
    
    # Execute V2
    rec = calculate_bolus_v2(
        request=req_v2,
        settings=user_settings,
        iob_u=iob_u or 0.0,
        glucose_info=glucose_info
    )
    if iob_info and iob_info.status in ["unavailable", "stale"]:
        rec.warnings.append(f"IOB {iob_info.status}; se asumió 0 U para el cálculo del bot.")

    # Override if manual input was given (but keep breakdown for reference if possible, or just overwrite)
    if insulin_req is not None:
        rec.total_u_final = insulin_req
        rec.total_u = insulin_req
        rec.explain.append(f"Override: Usuario solicitó explícitamente {insulin_req} U")

    # 3. Message Generation (Strict Format)
    # ---------------------------------------------------------

    # 4. Message Generation (Strict Format)
    # ---------------------------------------------------------
    # Sugerencia: **2.5 U**
    # - Carbos: 22.5g → 2.25 U
    # - Corrección: +0.25 U (131 → target 110)
    # - IOB: −0.0 U
    # - Redondeo: 0.5 U
    # (request abc123)

    lines = []
    lines.append(f"Sugerencia: **{rec.total_u_final} U**")
    
    # Breakdown Analysis
    # We can try to reconstruct lines from 'explain' or use raw values
    # Rec has: meal_bolus_u, correction_u, iob_u.
    
    # A) Carbs
    if carbs > 0:
        cr = rec.used_params.cr_g_per_u
        lines.append(f"- Carbos: {carbs}g → {rec.meal_bolus_u:.2f} U")
    else:
        lines.append(f"- Carbos: 0g")

    # B) Correction
    # Logic: (Current - Target). 
    # Rec has correction_u.
    targ_val = rec.used_params.target_mgdl
    if rec.correction_u != 0:
        sign = "+" if rec.correction_u > 0 else ""
        lines.append(f"- Corrección: {sign}{rec.correction_u:.2f} U ({bg_val:.0f} → {targ_val:.0f})")
    elif bg_val is not None:
         # Explicit "0 U" if bg known
         lines.append(f"- Corrección: 0.0 U ({bg_val:.0f} → {targ_val:.0f})")
    else:
         lines.append(f"- Corrección: 0.0 U (Falta Glucosa)")

    # C) IOB
    # Rec IOB is positive, but we subtract it.
    if rec.iob_u > 0:
        lines.append(f"- IOB: −{rec.iob_u:.2f} U")
    else:
        lines.append(f"- IOB: −0.0 U")

    # D) Rounding / Adjustment
    # Total Raw vs Total Final
    # Raw = Meal + Corr - IOB
    starting = rec.meal_bolus_u + rec.correction_u - rec.iob_u
    if starting < 0: starting = 0
    
    diff = rec.total_u_final - starting
    if abs(diff) > 0.01:
         sign = "+" if diff > 0 else ""
         lines.append(f"- Ajuste/Redondeo: {sign}{diff:.2f} U")
    
    # Request ID
    lines.append(f"(`{request_id}`)")

    # E) Fiber Transparency
    # Check if engine deducted fiber
    fiber_msg = next((x for x in rec.explain if "Fibra" in x or "Restando" in x), None)
    if fiber_msg:
        # User Feedback
        lines.append(f"ℹ️ {fiber_msg}")
        # Persistence
        notes += f" [{fiber_msg}]"
    
    msg_text = "\n".join(lines)

    # 4. Save Snapshot
    SNAPSHOT_STORAGE[request_id] = {
        "rec": rec,
        "carbs": carbs,
        "bg": bg_val,
        "notes": notes,
        "source": "CalculateBolus",
        "ts": datetime.now()
    }
    logger.info(f"Snapshot saved for request_{request_id}. Keys: {len(SNAPSHOT_STORAGE)}")
    
    # 5. Send Card
    # ---------------------------------------------------------
    from app.services.async_injection_manager import AsyncInjectionManager
    injection_mgr = AsyncInjectionManager("admin")
    next_site = await injection_mgr.get_next_site("bolus")
    
    # Enrich message with recommendation
    msg_text += f"\n\n📍 Sugerencia: {next_site['name']} {next_site['emoji']}"

    
    # Callback: "accept|{request_id}"
    keyboard = [
        [
            InlineKeyboardButton(f"✅ Poner {rec.total_u_final} U", callback_data=f"accept|{request_id}"),
            InlineKeyboardButton("✏️ Cantidad", callback_data=f"edit_dose|{rec.total_u_final}|{request_id}"),
            InlineKeyboardButton("❌ Ignorar", callback_data=f"cancel|{request_id}")
        ],
        [
            InlineKeyboardButton("🌅 Desayuno", callback_data=f"set_slot|breakfast|{request_id}"),
            InlineKeyboardButton("🍕 Comida", callback_data=f"set_slot|lunch|{request_id}"),
            InlineKeyboardButton("🍽️ Cena", callback_data=f"set_slot|dinner|{request_id}"),
            InlineKeyboardButton("🥨 Snack", callback_data=f"set_slot|snack|{request_id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    logger.info(f"Bot creating inline keyboard for request_{request_id}")
    await reply_text(update, context, msg_text, reply_markup=reply_markup, parse_mode="Markdown")

    # Send Image
    try:
        from app.bot.image_renderer import generate_injection_image
        base_dir = Path(__file__).parent.parent / "static" / "assets"
        img_bytes = generate_injection_image(next_site["id"], base_dir)
        if img_bytes:
             await context.bot.send_photo(chat_id=update.effective_chat.id, photo=img_bytes)
    except Exception as e:
        logger.warning(f"Failed to send recommendation image: {e}")






async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photo Handler - Vision Layer."""
    if not await _check_auth(update, context): return
    
    photo = update.message.photo[-1] # Largest size
    
    # Notify user
    await reply_text(update, context, "👀 Analizando plato con Gemini Vision...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)

    try:
        # Download file (in memory)
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        
        # Fetch Settings/Keys
        user_settings = await get_bot_user_settings(update.effective_user.username)
        gemini_key = user_settings.vision.gemini_key
        
        # Call AI
        raw_response = await ai.analyze_image(image_bytes, api_key=gemini_key)
        
        # Parse JSON
        import json
        clean_json = raw_response.replace("```json", "").replace("```", "").strip()
        data = {}
        try:
            data = json.loads(clean_json)
        except json.JSONDecodeError:
            # Fallback if AI returned plain text
            await reply_text(update, context, f"🍽️ **Análisis**:\n{raw_response}")
            return

        # Format Message
        total_carbs = data.get("total_carbs", 0)
        advice = data.get("consejo", "")
        foods = data.get("alimentos", [])
        
        lines = ["🍽️ **Análisis de Plato**", ""]
        for f in foods:
             lines.append(f"• {f.get('nombre', '?')}: {f.get('g_carbo', 0)}g")
             
        lines.append("")
        lines.append(f"**Total: {total_carbs}g HC**")
        if advice:
            lines.append(f"\n💡 _{advice}_")
            
        msg_text = "\n".join(lines)
        
        # Buttons
        buttons = []
        if total_carbs > 0:
            # Use chat_bolus callback which triggers calculator flow
            # Format: chat_bolus_{units}_{carbs} -> Wait, chat_bolus_edit_ expects carbs?
            # Check callback handler: 
            # if data.startswith("chat_bolus_edit_"): carbs = ...
            # We want to TRIGGER calculation.
            # Best way: Trigger the /bolo command logic or simpler:
            # Provide a button that says "Calculate" and calls a callback that initiates calculation.
            # "chat_bolus_edit_{carbs}" seems to prompt for carb entry edit.
            # Let's use a NEW callback or reuse 'tool_wrapper_bolo' logic?
            # Actually, let's use a callback "vision_calc_{carbs}" that calls compute?
            # Or simpler: "chat_bolus_edit_{carbs}" prompts user to confirm/edit carbs. That's safer.
            buttons.append([
                InlineKeyboardButton(f"💉 Calcular para {total_carbs}g", callback_data=f"chat_bolus_edit_{total_carbs}")
            ])
        
        reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
        
        await reply_text(update, context, msg_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await reply_text(update, context, "❌ Error procesando la imagen.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Voice note handler."""
    if not await _check_auth(update, context):
        return

    voice_msg = update.message.voice or update.message.audio
    if not voice_msg:
        return

    if not config.is_telegram_voice_enabled() or not config.get_google_api_key():
        await reply_text(update, context, "El reconocimiento de voz no está configurado, envíame el texto.")
        return

    # Validations
    duration = getattr(voice_msg, "duration", None)
    if duration and duration > config.get_max_voice_seconds():
        await reply_text(
            update,
            context,
            f"La nota de voz es demasiado larga (> {config.get_max_voice_seconds()} s). Envía una más corta o texto."
        )
        return

    max_bytes = config.get_max_voice_bytes()
    file_size = getattr(voice_msg, "file_size", None)
    if file_size and file_size > max_bytes:
        await reply_text(
            update,
            context,
            f"El audio supera el límite de {config.get_max_voice_mb()} MB. Envía una nota más corta."
        )
        return

    await reply_text(update, context, "🎙️ Procesando nota de voz...")
    tmp_path = None
    try:
        file = await context.bot.get_file(voice_msg.file_id)
        file_bytes = await file.download_as_bytearray()

        if not file_size and len(file_bytes) > max_bytes:
            await reply_text(
                update,
                context,
                f"El audio supera el límite de {config.get_max_voice_mb()} MB. Envía una nota más corta."
            )
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        # Determine Gemini Model from User Settings
        user_settings = await get_bot_user_settings(update.effective_user.username)
        model_name = user_settings.vision.gemini_transcribe_model or config.get_gemini_transcribe_model()
        
        mime_type = voice_msg.mime_type or "audio/ogg"
        result = await voice.transcribe_audio(file_bytes, mime_type=mime_type, model_name=model_name)

        if result.error:
            error_code = result.error
            if error_code == "missing_key":
                await reply_text(update, context, "El reconocimiento de voz no está configurado, envíame el texto.")
            elif error_code == "unsupported_format":
                await reply_text(update, context, "Formato de audio no soportado. Envía un OGG/OPUS o escribe el texto.")
            elif error_code == "too_large":
                await reply_text(
                    update,
                    context,
                    f"La nota de voz supera el límite de {config.get_max_voice_mb()} MB. Envía una más corta."
                )
            else:
                await reply_text(update, context, "No se pudo transcribir la nota de voz. Inténtalo de nuevo o escribe el texto.")
            return

        transcript = (result.text or "").strip()
        confidence = result.confidence if result.confidence is not None else 1.0
        if not transcript or confidence < config.get_voice_min_confidence():
            context.user_data["pending_voice_text"] = transcript
            display_text = transcript if transcript else "(sin texto)"
            keyboard = [
                [
                    InlineKeyboardButton("✅ Sí", callback_data="voice_confirm_yes"),
                    InlineKeyboardButton("✏️ Repetir", callback_data="voice_confirm_retry"),
                    InlineKeyboardButton("❌ Cancelar", callback_data="voice_confirm_cancel"),
                ]
            ]
            await reply_text(
                update,
                context,
                f"No estoy seguro de haber entendido la nota de voz. He captado: “{display_text}”. ¿Es correcto?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        # Re-route as text
        await _process_text_input(update, context, transcript)
    except Exception as exc:
        logger.error("Voice handler failed: %s", exc)
        await reply_text(update, context, "❌ Error transcribiendo la nota de voz.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                logger.debug("Failed to cleanup temp audio file %s", tmp_path)


async def morning_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger morning summary on demand."""
    if not await _check_auth(update, context): 
        return

    mode = "full"
    if context.args and "alerts" in context.args[0].lower():
        mode = "alerts"
        
    health.record_action(f"cmd:morning", True, f"mode={mode}")
    
    await proactive.morning_summary(
        username=update.effective_user.username,
        chat_id=update.effective_chat.id,
        trigger="manual",
        mode=mode
    )

async def run_glucose_monitor_job() -> None:
    """
    Lightweight wrapper to run the proactive glucose monitoring pipeline.
    Keeps health metrics updated and no-ops when the bot is disabled.
    """
    logger.info("Running glucose monitor job...")
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
    except Exception as exc:
        logger.error("Glucose monitor job failed to load settings: %s", exc)
        health.record_action("job:glucose_monitor", False, f"settings_error:{exc}")
        return

    if not user_settings.bot.enabled:
        health.record_action("job:glucose_monitor", False, "bot_disabled")
        return

    try:
        await proactive.trend_alert(trigger="auto")
        health.record_action("job:glucose_monitor", True)
    except Exception as exc:
        logger.error("Glucose monitor job failed: %s", exc)
        health.record_action("job:glucose_monitor", False, str(exc))
        raise

def create_bot_app() -> Application:
    """Factory to create and configure the PTB Application."""
    token = config.get_telegram_bot_token()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Bot will not run.")
        return None

    application = (
        Application.builder()
        .token(token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .build()
    )

    # Register Handlers
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("morning", morning_command))
    
    # Operational Commands (Capability Registry)
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("capabilities", capabilities_command))
    application.add_handler(CommandHandler("tools", tools_command))
    application.add_handler(CommandHandler("jobs", jobs_command))
    application.add_handler(CommandHandler("run", run_job_command))
    
    # Tool Wrappers
    application.add_handler(CommandHandler("bolo", tool_wrapper_bolo))
    application.add_handler(CommandHandler("corrige", tool_wrapper_corrige))
    application.add_handler(CommandHandler("whatif", tool_wrapper_whatif))
    application.add_handler(CommandHandler("stats", tool_wrapper_stats))
    application.add_handler(CommandHandler("btn", btn_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
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
    global _polling_task
    
    mode, reason = decide_bot_mode()
    health.enabled = mode != BotMode.DISABLED
    health.set_mode(mode, reason)
    health.set_started()

    logger.info("Telegram bot: %s", "enabled" if health.enabled else "disabled")
    logger.info("Mode selected: %s (reason: %s)", mode.value, reason)
    public_url_probe, public_url_source_probe = config.get_public_bot_url_with_source()
    logger.info("Public URL detected: %s (source: %s)", "yes" if public_url_probe else "no", public_url_source_probe)
    logger.info("ENABLE_TELEGRAM_BOT=%s. Allowed user: %s", os.environ.get("ENABLE_TELEGRAM_BOT", "true"), config.get_allowed_telegram_user_id())
    voice_enabled = config.is_telegram_voice_enabled() and bool(config.get_google_api_key())
    logger.info("Voice notes: %s (provider: Gemini)", "enabled" if voice_enabled else "disabled")
    if not config.get_allowed_telegram_user_id():
        logger.warning("ALLOWED_TELEGRAM_USER_ID missing; bot will warn user on /start.")

    # Diagnostic: Check Timezone Availability
    try:
        from app.utils.timezone import DEFAULT_TIMEZONE, get_user_timezone
        tz_check = get_user_timezone() # Should be Madrid defaults
        logger.info(f"Timezone System Check: Default='{DEFAULT_TIMEZONE}' -> Resolved={tz_check}")
    except Exception as e:
        logger.warning(f"Timezone System Check: FAILED ({e}). specific time features might be affected.")

    if mode == BotMode.DISABLED:
        return

    _bot_app = create_bot_app()
    if not _bot_app:
        health.set_mode(BotMode.ERROR, reason)
        health.set_error("No TELEGRAM_BOT_TOKEN")
        return

    # Track updates for both webhook and polling modes
    _bot_app.add_handler(MessageHandler(filters.ALL, _mark_update_handler), group=100)

    public_url, public_url_source = config.get_public_bot_url_with_source()
    webhook_secret = config.get_telegram_webhook_secret()

    # Initialize the app (coroutines)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            await _bot_app.initialize()
            await _bot_app.start()
            logger.info("✅ Bot initialized and started successfully.")
            break
        except Exception as e:
            logger.error(f"⚠️ Bot initialization attempt {attempt + 1}/{max_retries} failed: {e}")
            health.set_error(str(e))
            if attempt < max_retries - 1:
                wait_time = 2 * (attempt + 1)
                logger.info(f"Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.critical("❌ All bot initialization attempts failed. Bot service will be unavailable.")
                _bot_app = None
                health.set_mode(BotMode.ERROR, reason)
                return

    if mode == BotMode.WEBHOOK and public_url:
        webhook_url = f"{public_url}/api/webhook/telegram"
        logger.info("Webhook URL configured: %s", _sanitize_url(webhook_url))
        try:
            await _set_webhook(url=webhook_url, secret_token=webhook_secret)
            health.clear_error()
            health.set_mode(BotMode.WEBHOOK, reason)
            return
        except Exception as exc:
            logger.warning("Failed to set webhook, falling back to polling: %s", exc)
            health.set_error(str(exc))

    # Polling fallback
    poll_interval = config.get_bot_poll_interval()
    read_timeout = config.get_bot_read_timeout()
    fallback_reason = "missing_public_url" if not public_url else "webhook_failed"
    backoff_schedule = [1, 2, 5, 10, 20, 30]

    async def _start_polling_with_retry() -> None:
        nonlocal backoff_schedule
        for attempt, delay in enumerate(backoff_schedule, start=1):
            try:
                await _bot_app.updater.start_polling(
                    poll_interval=poll_interval,
                    timeout=read_timeout,
                    bootstrap_retries=2,
                )
                health.set_mode(BotMode.POLLING, fallback_reason)
                logger.info("Polling started (interval=%s, timeout=%s)", poll_interval, read_timeout)
                return
            except Exception as exc:
                msg = f"Polling start attempt {attempt} failed: {exc}"
                logger.warning(msg)
                health.set_error(str(exc))
                await asyncio.sleep(delay)
        # Last attempt without further delay
        try:
            await _bot_app.updater.start_polling(
                poll_interval=poll_interval,
                timeout=read_timeout,
                bootstrap_retries=2,
            )
            health.set_mode(BotMode.POLLING, fallback_reason)
            logger.info("Polling started after retries (interval=%s, timeout=%s)", poll_interval, read_timeout)
        except Exception as exc:
            logger.error("Failed to start polling after retries: %s", exc)
            health.set_mode(BotMode.ERROR, "polling_failed")
            health.set_error(str(exc))

    logger.info("Polling enabled (background).")
    _polling_task = asyncio.create_task(_start_polling_with_retry(), name="telegram-bot-polling")

async def shutdown() -> None:
    """Called on FastAPI shutdown."""
    global _bot_app
    global _polling_task
    
    if _polling_task:
        logger.info("Canceling Telegram polling task...")
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            logger.info("Polling task cancelled.")
        except Exception as e:
            logger.error(f"Error cancelling polling task: {e}")
            
    if _bot_app:
        logger.info("Shutting down Telegram Bot...")
        try:
            await _bot_app.updater.stop()
        except Exception:
            pass
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
        health.mark_update()
        await _bot_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing Telegram update: {e}")
        health.set_error(str(e))


def _sanitize_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        sanitized = parsed._replace(query="", fragment="")
        return urlunparse((sanitized.scheme, sanitized.netloc, sanitized.path, "", "", ""))
    except Exception:
        return url


def get_bot_application() -> Optional[Application]:
    return _bot_app


async def _set_webhook(url: str, secret_token: Optional[str]) -> None:
    if not _bot_app:
        raise RuntimeError("Bot application not initialized")

    set_webhook_kwargs = {
        "url": url,
        "drop_pending_updates": True,
        "allowed_updates": ["message", "callback_query"],
    }
    if secret_token:
        set_webhook_kwargs["secret_token"] = secret_token

    await _bot_app.bot.set_webhook(**set_webhook_kwargs)


async def refresh_webhook_registration() -> Dict[str, Any]:
    """
    Recompute expected webhook URL and call setWebhook again.
    Returns dict with ok/error and webhook info.
    """
    public_url, source = config.get_public_bot_url_with_source()
    webhook_secret = config.get_telegram_webhook_secret()

    expected_url = f"{public_url}/api/webhook/telegram" if public_url else None
    if not expected_url:
        return {
            "ok": False,
            "error": "missing_public_url",
            "expected_webhook_url": None,
            "public_url_source": source,
            "telegram_webhook_info": None,
        }

    if not _bot_app:
        return {
            "ok": False,
            "error": "bot_not_initialized",
            "expected_webhook_url": _sanitize_url(expected_url),
            "public_url_source": source,
            "telegram_webhook_info": None,
        }

    try:
        await _set_webhook(url=expected_url, secret_token=webhook_secret)
        health.clear_error()
        result_ok = True
        log_msg = "webhook refreshed ok"
    except Exception as exc:
        health.set_error(str(exc))
        result_ok = False
        log_msg = f"webhook refreshed fail: {exc}"
    logger.info(log_msg)

    info = None
    try:
        info_obj = await _bot_app.bot.get_webhook_info()
        info = {
            "url": _sanitize_url(info_obj.url) if info_obj else None,
            "has_custom_certificate": getattr(info_obj, "has_custom_certificate", None),
            "pending_update_count": getattr(info_obj, "pending_update_count", None),
            "last_error_date": getattr(info_obj, "last_error_date", None),
            "last_error_message": getattr(info_obj, "last_error_message", None),
            "max_connections": getattr(info_obj, "max_connections", None),
            "ip_address": getattr(info_obj, "ip_address", None),
        }
    except Exception as exc:
        if result_ok:
            health.set_error(str(exc))

    return {
        "ok": result_ok,
        "error": None if result_ok else health.last_error,
        "expected_webhook_url": _sanitize_url(expected_url),
        "public_url_source": source,
        "telegram_webhook_info": info,
    }


async def _mark_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Passive handler to mark last update time without altering behaviour."""
    health.mark_update()


DRAFT_MSG_CACHE: Dict[int, int] = {}

async def on_draft_updated(username: str, draft: Any, action: str) -> None:
    """
    Notifies user about an active draft update.
    """
    global _bot_app
    if not _bot_app: return

    # Resolve Chat ID
    # Priority: 
    # 1. Configured allowed ID (security)
    # 2. Look up in settings (if we had a map)
    # For now, default to single-user admin ID
    chat_id = config.get_allowed_telegram_user_id()
    
    if not chat_id:
        return

    macros_txt = draft.total_macros()
    # Map action to user friendly
    action_map = {
        "updated_add": "AÑADIDO",
        "updated_replace": "CORREGIDO",
        "created": "CREADO"
    }
    action_str = action_map.get(action, action.upper()).replace("_", " ")
    
    msg_txt = f"📝 **Comida en curso**\n\nActualizado: `{macros_txt}`\nEstado: **{action_str}**\n\nSigo esperando más datos..."
    
    # Inline Button to Close directly
    kb = [
        [
            InlineKeyboardButton("✅ Confirmar Ahora", callback_data=f"draft_confirm|{username}|{draft.id}"),
            InlineKeyboardButton("✏️ Editar", callback_data=f"draft_edit|{username}|{draft.id}")
        ],
        [
            InlineKeyboardButton("❌ Descartar", callback_data=f"draft_discard|{username}|{draft.id}")
        ]
    ]
    
    markup = InlineKeyboardMarkup(kb)
    sent_msg = None
    
    # Try Edit Existing
    last_msg_id = DRAFT_MSG_CACHE.get(chat_id)
    if last_msg_id:
        try:
            # Use bot.edit_message_text directly (not via wrapper which expects CallbackQuery)
            await _bot_app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=last_msg_id,
                text=msg_txt,
                reply_markup=markup,
                parse_mode="Markdown"
            )
            logger.info(f"Draft message edited successfully (msg_id={last_msg_id})")
            return # Edited successfully
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.info("Draft edit skipped (content identical)")
                return
            # If error (message deleted, too old), fall back to send new
            logger.info(f"Draft edit failed ({e}), sending new.")
            DRAFT_MSG_CACHE.pop(chat_id, None)
        except Exception as e:
            logger.info(f"Draft edit failed ({e}), sending new.")
            DRAFT_MSG_CACHE.pop(chat_id, None)

    # Send New
    try:
        sent_msg = await bot_send(
            chat_id=chat_id,
            text=msg_txt,
            bot=_bot_app.bot,
            reply_markup=markup,
            log_context="draft_update",
            parse_mode="Markdown"
        )
        if sent_msg:
             DRAFT_MSG_CACHE[chat_id] = sent_msg.message_id
    except Exception as e:
        logger.error(f"Failed to send draft update: {e}")

async def on_new_meal_received(carbs: float, fat: float, protein: float, fiber: float, source: str, origin_id: Optional[str] = None) -> None:
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

    logger.info(f"Bot proactively notifying meal: {carbs}g F:{fat} P:{protein} Fib:{fiber} from {source} (id={origin_id})")
    now_utc = datetime.now(timezone.utc)
    settings = get_settings()

    # Warsaw Observability
    try:
        if hasattr(settings, "warsaw") and settings.warsaw.enabled:
             if (fat or 0) + (protein or 0) < 1.0:
                 logger.info("mfp_missing_kcal_warsaw_skipped: Low/Missing Fat/Protein data from MFP")
    except Exception: pass
    
    # 1. Gather Context
    store = DataStore(Path(settings.data.data_dir))
    user_settings = await get_bot_user_settings() # NEW (DB)
    
    bg_val = None
    bg_trend = None
    bg_source = "none"
    bg_age = 0.0
    bg_datetime: Optional[datetime] = None
    iob_u = 0.0

    # Use shared context tool for IOB and other context (but override glucose with explicit priority logic)
    ctx_res = await tools.get_status_context(user_settings=user_settings)
    if not isinstance(ctx_res, tools.ToolError):
        # Use the context result directly if available, as it has the best logic
        if ctx_res.iob_u is not None:
             iob_u = ctx_res.iob_u
        
        # Prefer the glucose from get_status_context as it is validated and robust
        if ctx_res.bg_mgdl is not None:
             bg_val = ctx_res.bg_mgdl
             bg_trend = ctx_res.direction
             bg_source = ctx_res.source
             
             # Calculate age from the timestamp provided by context
             if ctx_res.timestamp:
                 try:
                     ts = datetime.fromisoformat(ctx_res.timestamp)
                     if ts.tzinfo is None:
                         ts = ts.replace(tzinfo=timezone.utc)
                     bg_datetime = ts
                 except Exception:
                     bg_datetime = datetime.now(timezone.utc)
    
    # Only fallback to custom fetching if get_status_context failed to provide glucose
    fetched = bg_val is not None

    prefer_nightscout = user_settings.nightscout.enabled and user_settings.nightscout.url
    dexcom_ready = user_settings.dexcom and user_settings.dexcom.enabled and user_settings.dexcom.username
    ns_url = user_settings.nightscout.url or settings.nightscout.base_url

    async def _fetch_from_nightscout() -> bool:
        nonlocal bg_val, bg_trend, bg_datetime, bg_source
        if not ns_url:
            return False
        token = user_settings.nightscout.token or settings.nightscout.token
        client = NightscoutClient(base_url=ns_url, token=token, timeout_seconds=5)
        try:
            sgv = await client.get_latest_sgv()
            if not sgv:
                return False
            bg_val = float(sgv.sgv)
            bg_trend = sgv.direction
            bg_source = "nightscout"
            try:
                bg_datetime = datetime.fromtimestamp(int(sgv.date) / 1000, tz=timezone.utc)
            except Exception as exc:
                logger.warning(f"Nightscout datetime parse failed, defaulting to now: {exc}")
                bg_datetime = datetime.now(timezone.utc)
            return True
        except Exception as exc:
            logger.warning(f"Nightscout fetch failed: {exc}")
            return False
        finally:
            await client.aclose()

    async def _fetch_from_dexcom() -> bool:
        nonlocal bg_val, bg_trend, bg_datetime, bg_source
        if not (dexcom_ready and user_settings.dexcom.password):
            return False
        try:
            dex_client = DexcomClient(
                username=user_settings.dexcom.username,
                password=user_settings.dexcom.password,
                region=user_settings.dexcom.region or "ous",
            )
            bg = await dex_client.get_latest_sgv()
            if not bg:
                return False
            bg_val = float(bg.sgv)
            bg_trend = bg.trend
            bg_datetime = bg.date
            bg_source = "dexcom"
            return True
        except Exception as exc:
            logger.warning(f"Dexcom fetch failed: {exc}")
            return False

    async def _fetch_from_local_db() -> bool:
        nonlocal bg_val, bg_trend, bg_datetime, bg_source
        try:
            async with SessionLocal() as session:
                from sqlalchemy import text
                stmt = text("SELECT sgv, date FROM entries ORDER BY date DESC LIMIT 1")
                row = (await session.execute(stmt)).fetchone()
                if not row:
                    return False
                bg_val = float(row.sgv)
                try:
                    bg_datetime = datetime.fromtimestamp(int(row.date) / 1000, tz=timezone.utc)
                except Exception as exc:
                    logger.warning(f"Local DB datetime parse failed, defaulting to now: {exc}")
                    bg_datetime = datetime.now(timezone.utc)
                bg_source = "local_db"
                return True
        except Exception as exc:
            logger.warning(f"Local DB glucose fallback failed: {exc}")
            return False

    if not fetched:
        if prefer_nightscout:
            fetched = await _fetch_from_nightscout()
            if not fetched and dexcom_ready:
                fetched = await _fetch_from_dexcom()
        elif dexcom_ready:
            fetched = await _fetch_from_dexcom()
            if not fetched and prefer_nightscout:
                fetched = await _fetch_from_nightscout()
    
    if not fetched:
        await _fetch_from_local_db()

    if bg_datetime:
        bg_age = max(0.0, (now_utc - bg_datetime).total_seconds() / 60.0)

    
    # 2. Calculate Bolus V2 (Snapshot Safe)
    # -----------------------------------------------------
    request_id = str(uuid.uuid4())[:8]

    slot = get_current_meal_slot(user_settings)
    
    # calculate staleness
    is_stale_reading = False
    if bg_datetime and bg_age > 20:
         is_stale_reading = True
         logger.warning(f"Glucose reading is stale! Age: {bg_age:.1f} mins")
    
    glucose_info = GlucoseUsed(
        mgdl=bg_val,
        source=bg_source,
        trend=bg_trend,
        is_stale=is_stale_reading
    )
    
    req_v2 = BolusRequestV2(
        carbs_g=carbs,
        fat_g=fat,
        protein_g=protein,
        fiber_g=fiber,
        meal_slot=slot,
        bg_mgdl=bg_val,
        target_mgdl=user_settings.targets.mid
    )
    
    rec = calculate_bolus_v2(
        request=req_v2,
        settings=user_settings,
        iob_u=iob_u,
        glucose_info=glucose_info
    )

    # Store Snapshot
    SNAPSHOT_STORAGE[request_id] = {
        "rec": rec,
        "carbs": carbs,
        "fat": fat,
        "protein": protein,
        "fiber": fiber,
        "source": source,
        "origin_id": origin_id,
        "ts": datetime.now()
    }

    # 3. Message (Strict Format matching Core Engine)
    # -----------------------------------------------------
    rec_u = rec.total_u_final
    
    lines = []
    # Sanitize source for Markdown
    safe_source = source.replace("_", "\\_") if source else "Unknown"
    lines.append(f"🍽️ **Nueva Comida Detectada** ({safe_source})")
    lines.append("")
    lines.append(f"Resultado: **{rec_u} U**")
    lines.append("")
    
    # Use the explanation from the core engine to match App exactly
    if rec.explain:
        for ex in rec.explain:
            lines.append(f"• {ex}")
            
    lines.append("")
    lines.append(f"Total Calculado: {rec.total_u_raw:.2f} (Base) → {rec.total_u_final} U (Final)")
    lines.append("")
    lines.append(f"¿Registrar {rec_u} U?")
    
    msg_text = "\n".join(lines)
    
    keyboard = [
        [
            InlineKeyboardButton(f"✅ Poner {rec_u} U", callback_data=f"accept|{request_id}"),
            InlineKeyboardButton("✏️ Cantidad", callback_data=f"edit_dose|{rec_u}|{request_id}"),
            InlineKeyboardButton("❌ Ignorar", callback_data=f"cancel|{request_id}")
        ],
        [
            InlineKeyboardButton("🌅 Desayuno", callback_data=f"set_slot|breakfast|{request_id}"),
            InlineKeyboardButton("🍕 Comida", callback_data=f"set_slot|lunch|{request_id}"),
            InlineKeyboardButton("🍽️ Cena", callback_data=f"set_slot|dinner|{request_id}"),
            InlineKeyboardButton("🥨 Snack", callback_data=f"set_slot|snack|{request_id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await bot_send(
            chat_id=chat_id,
            text=msg_text,
            bot=_bot_app.bot,
            reply_markup=reply_markup,
            parse_mode="Markdown",
            log_context="proactive_meal",
        )
    except Exception as e:
        logger.error(f"Failed to send proactive message: {e}")

async def btn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Debug command to test inline buttons."""
    if not await _check_auth(update, context): return
    
    test_id = str(uuid.uuid4())[:8]
    keyboard = [
        [
            InlineKeyboardButton("✅ TEST", callback_data=f"test|{test_id}"),
            InlineKeyboardButton("❌ CANCEL", callback_data=f"cancel|{test_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    logger.info(f"Sending /btn debug message with markup: {type(reply_markup).__name__}")
    logger.info(f"Buttons: {[[b.callback_data for b in row] for row in keyboard]}")
    
    await reply_text(update, context, "🔘 **Botón de Pruebas**\nPulsa para verificar callback delivery.", reply_markup=reply_markup, parse_mode="Markdown")


async def _handle_snapshot_callback(query, data: str) -> None:
    try:
        units_override = None
        
        if data.startswith("accept_manual|"):
            # accept_manual|units|uuid
            parts = data.split("|")
            units_override = float(parts[1])
            request_id = parts[2]
            is_accept = True
        elif "|" in data:
            action_prefix, request_id = data.split("|", 1)
            is_accept = (action_prefix == "accept" or action_prefix == "accept_manual")
        else:
            # Legacy fallback
            request_id = data.split("_")[-1]
            is_accept = "accept_bolus_" in data

        snapshot = SNAPSHOT_STORAGE.get(request_id)
        
        if not snapshot:
            # Try looking up by full data just in case it was stored weirdly
            snapshot = SNAPSHOT_STORAGE.get(data)
        
        if not snapshot:
            logger.warning(f"Snapshot missing for req={request_id}. Available count={len(SNAPSHOT_STORAGE)}")
            health.record_action(f"callback:{'accept' if is_accept else 'cancel'}:{request_id}", False, "snapshot_missing")
            await edit_message_text_safe(query, f"⚠️ Error: No encuentro el snapshot ({request_id}). Recalcula.")
            return

        # --- Handle Cancellation (Ignorar) ---
        if not is_accept:
             origin_id = snapshot.get("origin_id")
             base_text = query.message.text if query.message else ""
             if origin_id:
                  try:
                      async with SessionLocal() as session:
                           from sqlalchemy import text
                           await session.execute(text("DELETE FROM treatments WHERE id = :oid"), {"oid": origin_id})
                           await session.commit()
                      await edit_message_text_safe(query, f"{base_text}\n\n🗑️ Descartado y borrado.")
                  except Exception as e:
                      logger.error(f"Failed to delete ignored treatment: {e}")
                      await edit_message_text_safe(query, f"{base_text}\n\n❌ Descartado (Error al borrar: {e})")
             else:
                  await edit_message_text_safe(query, f"{base_text}\n\n❌ Descartado.")
             
             SNAPSHOT_STORAGE.pop(request_id, None)
             return
            
        if "rec" in snapshot:
             rec: BolusResponseV2 = snapshot["rec"]
             carbs = snapshot["carbs"]
             units = units_override if units_override is not None else rec.total_u_final
        elif "units" in snapshot:
             # AI Router Snapshot
             units = units_override if units_override is not None else snapshot["units"]
             carbs = snapshot.get("carbs", 0)
        else:
             await edit_message_text_safe(query, "⚠️ Error: Snapshot irreconocible.")
             return

        if units < 0:
             health.record_action(f"callback:accept:{request_id}", False, "negative_dose")
             await query.answer("Error: Dosis negativa")
             await edit_message_text_safe(query, "⛔ Error: Dosis negativa.")
             return

        notes = snapshot.get("notes", "Bolus Bot V2")
        if snapshot.get("source"):
             notes += f" ({snapshot['source']})"
        
        fat = snapshot.get("fat", 0.0)
        protein = snapshot.get("protein", 0.0)
        fiber = snapshot.get("fiber", 0.0)
        origin_id = snapshot.get("origin_id")
        
        # Execute Action
        add_args = {"insulin": units, "carbs": carbs, "fat": fat, "protein": protein, "fiber": fiber, "notes": notes, "replace_id": origin_id}
        result = await tools.add_treatment(add_args)
        
        base_text = query.message.text if query.message else ""

        if isinstance(result, tools.ToolError) or not getattr(result, "ok", False):
            error_msg = result.message if isinstance(result, tools.ToolError) else (result.ns_error or "Error")
            health.record_action(f"callback:accept:{request_id}", False, error_msg)
            await edit_message_text_safe(query, text=f"{base_text}\n\n❌ Error: {error_msg}", parse_mode="Markdown")
            return

        success_msg = f"{base_text}\n\nRegistrado ✅ {units} U"
        if carbs > 0: success_msg += f" / {carbs} g"
        if fiber > 0: success_msg += f" (Fibra: {fiber} g)"
        
        if getattr(result, "injection_site", None):
             site = result.injection_site
             success_msg += f"\n\n📍 Rotado. Siguiente: {site.get('name')} {site.get('emoji')}"
             
             # Send Image
             # Send Image with Overlay
             if site.get("image"):
                 try:
                     from app.bot.image_renderer import generate_injection_image
                     base_dir = Path(__file__).parent.parent / "static" / "assets"
                     logger.info(f"Resolving image for site={site.get('id')} image={site.get('image')} in {base_dir}")

                     site_id = site.get("id") 
                     img_bytes = None
                     
                     if site_id:
                         try:
                             img_bytes = generate_injection_image(site_id, base_dir)
                         except Exception as gen_e:
                             logger.error(f"Image generation error: {gen_e}")

                     if img_bytes:
                         logger.info(f"Sending generated injection image for {site_id}")
                         # Force unique filename to prevent caching, using readable name
                         safe_label = site['name'][:20].replace(" ", "_").replace(".", "").encode('ascii', 'ignore').decode('ascii')
                         img_bytes.name = f"inj_{safe_label}_{uuid.uuid4().hex[:6]}.png"
                         
                         # Use query.get_bot() since 'context' is not available in this helper scope
                         await query.get_bot().send_photo(chat_id=query.effective_chat.id, photo=img_bytes)
                     else:
                         # Fallback to static
                         img_path = base_dir / site["image"]
                         logger.info(f"Fallback to static image: {img_path}")
                         if img_path.exists():
                              await query.get_bot().send_photo(chat_id=query.effective_chat.id, photo=open(img_path, "rb"))
                         else:
                              logger.error(f"Static image not found: {img_path}")

                 except Exception as e:
                     logger.error(f"Failed to send injection image: {e}", exc_info=True)
        else:
             try:
                 from app.services.async_injection_manager import AsyncInjectionManager
                 mgr = AsyncInjectionManager("admin")
                 new_next = await mgr.rotate_site("bolus")
                 if new_next:
                     success_msg += f"\n\n📍 Rotado. Siguiente: {new_next['name']} {new_next['emoji']}"
             except Exception: pass

        # New Buttons
        kb_post = []
        if result.treatment_id:
             kb_post.append([
                 InlineKeyboardButton("✏️ Renombrar", callback_data=f"rename_txn|{result.treatment_id}"),
                 InlineKeyboardButton("⭐ Guardar Plato", callback_data=f"save_fav_txn|{result.treatment_id}")
             ])

        await edit_message_text_safe(query, text=success_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_post) if kb_post else None)
        SNAPSHOT_STORAGE.pop(request_id, None)
        health.record_action(f"callback:accept:{request_id}", True)

    except Exception as e:
        logger.error(f"Snapshot Callback error: {e}")
        health.record_action(f"callback:error", False, str(e))
        await edit_message_text_safe(query, text=f"Error fatal: {e}")

async def _update_basal_event(status: str, snooze_minutes: int = 0) -> None:
    """Helper to update basal daily status in DataStore."""
    try:
        settings = get_settings()
        store = DataStore(Path(settings.data.data_dir))
        events = store.load_events()
        
        from datetime import datetime
        import zoneinfo
        # Use simple date today for key
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d") # Or use local logic if consistent with proactive.py
        # proactive.py uses local time for date key. We should match it.
        # But for robustness, let's update the entry matching today's DATE (whatever proactive created).
        # Actually, if proactive created an entry "today", it used a date string.
        # Let's search for the LATEST basal_daily_status entry and check if it resembles "today".
        
        # Helper: Find entry
        entry = next((e for e in events if e.get("type") == "basal_daily_status" and e.get("date") == today_str), None)
        
        if not entry:
            # Fallback: Create one if missing (triggered manually e.g.)
            entry = {"type": "basal_daily_status", "date": today_str}
            events.append(entry)
            
        entry["status"] = status
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        if status == "snoozed" and snooze_minutes > 0:
             until = datetime.now(timezone.utc) + timedelta(minutes=snooze_minutes)
             entry["snooze_until"] = until.isoformat()
             
        store.save_events(events)
    except Exception as e:
        logger.error(f"Failed to update basal event: {e}")


async def send_autosens_alert(chat_id: int, ratio: float, slot: str, old_isf: float, new_isf: float, suggestion_id: str) -> None:
    """Sends a proactive Autosens Advice alert."""
    if not _bot_app: return

    pct = int((ratio - 1.0) * 100)
    emoji = "📉" if ratio < 1 else "📈"
    trend = "Sensibilidad" if ratio < 1 else "Resistencia"
    
    msg = (
        f"🔔 **Autosens Detectado**\n\n"
        f"He detectado un cambio de {trend} ({emoji} {pct}%).\n"
        f"Franja: **{slot.upper()}**\n\n"
        f"Tu ISF actual: `{old_isf}`\n"
        f"Sugerido: **{new_isf}**\n\n"
        f"¿Quieres actualizar tu perfil?"
    )
    
    keyboard = [
        [
            InlineKeyboardButton(f"✅ Aceptar ({new_isf})", callback_data=f"autosens_confirm|{suggestion_id}|{new_isf}|{slot}"),
            InlineKeyboardButton("❌ Descartar", callback_data=f"autosens_cancel|{suggestion_id}")
        ]
    ]
    
    try:
        await bot_send(
            chat_id=chat_id,
            text=msg,
            bot=_bot_app.bot,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
            log_context="autosens_alert"
        )
    except Exception as e:
        logger.error(f"Failed to send autosens alert: {e}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button clicks (Approve/Ignore)."""
    query = update.callback_query
    data = query.data
    
    # Debug Log
    logger.info(f"[Callback] received data='{data}' from_user={query.from_user.id}")
    
    # Always Answer
    try: await query.answer()
    except: pass

    # --- Draft Confirm ---
    if data.startswith("draft_confirm|"):
        try:
            parts = data.split("|")
            target_user = parts[1]
            draft_id = parts[2] if len(parts) > 2 else None
            from app.services.nutrition_draft_service import NutritionDraftService
            
            # Clear Cache for this chat as interaction ends or restarts
            chat_id = query.message.chat.id
            DRAFT_MSG_CACHE.pop(chat_id, None)

            async with SessionLocal() as session:
                 # Close Draft (DB)
                 treatment, created, draft_closed = await NutritionDraftService.close_draft_to_treatment(
                     target_user,
                     session,
                     draft_id=draft_id,
                 )
                 if treatment:
                     treatment_payload = {
                         "id": treatment.id,
                         "carbs": treatment.carbs,
                         "fat": treatment.fat,
                         "protein": treatment.protein,
                         "fiber": treatment.fiber,
                         "notes": treatment.notes,
                         "draft_id": treatment.draft_id,
                     }
                     if created:
                         session.add(treatment)
                     if created or draft_closed:
                         await session.commit()
                     logger.info(
                         "draft_confirmed",
                         extra={
                             "draft_id": treatment_payload["draft_id"],
                             "treatment_id": treatment_payload["id"],
                             "is_newly_created": created,
                         },
                     )
                     
                     await edit_message_text_safe(
                         query,
                         f"✅ **Borrador Confirmado**\n{treatment_payload['notes']}",
                     )
                     
                     # Handover to standard New Meal flow
                     if created:
                        await on_new_meal_received(
                            treatment_payload["carbs"],
                            treatment_payload["fat"],
                            treatment_payload["protein"],
                            treatment_payload["fiber"],
                            "draft_confirm",
                            origin_id=treatment_payload["id"],
                        )
                 else:
                    await edit_message_text_safe(query, "❌ No hay borrador activo o ya expiró.")
                
        except Exception as e:
            logger.error(f"Draft confirm error: {e}")
            await edit_message_text_safe(query, f"Error al confirmar: {e}")
        return

    # --- Draft Discard ---
    if data.startswith("draft_discard|"):
        try:
            parts = data.split("|")
            target_user = parts[1]
            draft_id = parts[2] if len(parts) > 2 else None
            from app.services.nutrition_draft_service import NutritionDraftService
            
            # Clear Cache
            chat_id = query.message.chat.id
            DRAFT_MSG_CACHE.pop(chat_id, None)

            async with SessionLocal() as session:
                 await NutritionDraftService.discard_draft(target_user, session, draft_id=draft_id)
                 await session.commit()
                 await edit_message_text_safe(query, "🗑️ **Borrador Descartado**")
        except Exception as e:
            logger.error(f"Draft discard error: {e}")
            await edit_message_text_safe(query, f"Error al descartar: {e}")
        return

    # --- Draft Edit ---
    if data.startswith("draft_edit|"):
        try:
            parts = data.split("|")
            target_user = parts[1]
            draft_id = parts[2] if len(parts) > 2 else None
            
            # Switch to "Manual Calculation" flow which allows editing carbs.
            # We can treat this as "I want to manually set the treatments carbs".
            # Or simpler: Ask for new value and update draft.
            
            # Since we have "chat_bolus_edit_" flow (Vision/Manual), let's reuse the concept.
            # But the simplest way for the user is: "Confirm this draft amount or change it?"
            # If they click edit, we can just say "Send me the new amount".
            # But handling that state is complex.
            
            # Better: Use the `edit_dose` style approach but for CARBS.
            # Let's prompt usage of /bolo command or simply ask for text.
            
            # ACTUALLY: The easiest way to "Edit" is to confirm it but jump to Bolus Calculation screen 
            # where you can edit the carbs in the confirmation card?
            # No, user wants to fix the DRAFT value.
            
            # Let's prompt for text input (Simple State)
            context.user_data["editing_draft_id"] = draft_id
            await edit_message_text_safe(query, 
                text=f"{query.message.text}\n\n✏️ **Editar Borrador**\nEscribe la cantidad correcta de hidratos (ej. 45):",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Draft edit error: {e}")
        return

    # --- Autosens Flow ---
    if data.startswith("autosens_confirm|"):
        # autosens_confirm|suggestion_id|new_isf|slot
        try:
            parts = data.split("|")
            sug_id = parts[1]
            new_val = float(parts[2])
            slot = parts[3]
            
            # 1. Update DB Settings
            user_settings = await get_bot_user_settings()
            username = user_settings.username or "admin"
            
            async with SessionLocal() as session:
                 # Fetch current raw settings
                 from app.services.settings_service import get_user_settings_service, update_user_settings_service
                 current_raw = await get_user_settings_service(username, session)
                 if current_raw and "settings" in current_raw:
                     s = current_raw["settings"]
                     # Navigate to cf -> slot
                     if "cf" not in s: s["cf"] = {}
                     s["cf"][slot] = new_val
                     
                     await update_user_settings_service(username, s, session)
                     
                     # 2. Mark Suggestion Accepted
                     from app.models.suggestion import ParameterSuggestion
                     from sqlalchemy import select
                     stmt = select(ParameterSuggestion).where(ParameterSuggestion.id == sug_id)
                     sug = (await session.execute(stmt)).scalars().first()
                     if sug:
                         sug.status = "accepted"
                         sug.applied_at = datetime.now(timezone.utc)
                     
                     await session.commit()
                         
            await edit_message_text_safe(query, f"✅ **Perfil Actualizado**\nISF {slot.upper()} ahora es {new_val}.")
            health.record_action("autosens_update", True)
            
        except Exception as e:
            logger.error(f"Autosens confirm failed: {e}")
            await edit_message_text_safe(query, f"❌ Error al actualizar: {e}")
        return

    if data.startswith("autosens_cancel|"):
        try:
            sug_id = data.split("|")[1]
            async with SessionLocal() as session:
                 from app.models.suggestion import ParameterSuggestion
                 from sqlalchemy import select
                 stmt = select(ParameterSuggestion).where(ParameterSuggestion.id == sug_id)
                 sug = (await session.execute(stmt)).scalars().first()
                 if sug:
                     sug.status = "rejected"
                     await session.commit()
            
            await edit_message_text_safe(query, "❌ Sugerencia descartada.")
        except Exception as e:
             logger.error(f"Autosens cancel failed: {e}")
        return


    # --- 0. Test Button ---
    if data.startswith("test|"):
        health.record_action("callback:test", True)
        
    # --- Generic Command Runner ---
    if data.startswith("run_cmd|"):
        # Format: run_cmd|command_name|arg1|arg2...
        # Simulates typing "/command arg1 arg2"
        parts = data.split("|")
        cmd_name = parts[1]
        args = parts[2:]
        
        # Map to handler functions directly if possible, or construct text update simulation
        # Simulation is easiest to ensure auth logic check.
        # But we are in callback query.
        # Let's call the wrapper function directly if recognized.
        
        if cmd_name == "corrige":
            await tool_wrapper_corrige(update, context) # Context args? We need to mock context.args
            # Wait, tool_wrapper_corrige reads context.args.
            # We need to set context.args manually.
            context.args = args
            await tool_wrapper_corrige(update, context)
            
        elif cmd_name == "bolo":
            context.args = args
            await tool_wrapper_bolo(update, context)
            
        elif cmd_name == "status":
            await status_command(update, context)
            
        else:
            await edit_message_text_safe(query, f"Comando desconocido en botón: {cmd_name}")
            
        health.record_action(f"callback:run_cmd:{cmd_name}", True)
        return
        await edit_message_text_safe(query, text=f"Recibido ✅ {data}")
        return

    # --- 1. ProActive / MFP Flow (Snapshot) ---
    if data.startswith("accept") or data.startswith("cancel|") or data.startswith("edit_dose|") or data.startswith("set_slot|"):
        # REMOVED: Early cancel interception that prevented DB cleanup.
        # Flow continues to _handle_snapshot_callback below.
             
        if data.startswith("edit_dose|"):
            try:
                # edit_dose|current_u|req_id
                parts = data.split("|")
                current_u = parts[1]
                req_id = parts[2]
                context.user_data["editing_bolus_request"] = req_id
                await edit_message_text_safe(query, 
                    text=f"{query.message.text}\n\n✏️ **Modo Edición**\nEscribe la nueva cantidad (sugerida: {current_u} U):",
                    parse_mode="Markdown"
                )
                health.record_action(f"callback:edit:{req_id}", True)
            except Exception as e:
                logger.error(f"Edit callback error: {e}")
            return

        if data.startswith("set_slot|"):
            try:
                # set_slot|slot|req_id
                _, slot, req_id = data.split("|")
                snapshot = SNAPSHOT_STORAGE.get(req_id)
                if not snapshot or "rec" not in snapshot:
                    await query.answer("Sesión caducada")
                    return
                
                # Recalcular
                old_rec = snapshot["rec"]
                user_settings = await get_bot_user_settings() # Fresh settings
                
                # Create NEW Request based on OLD one but changing slot
                # snapshot["rec"].used_params has some data
                # But it's better to use the original carbs/fat/protein
                
                req_v2 = BolusRequestV2(
                    carbs_g=snapshot["carbs"],
                    fat_g=snapshot.get("fat", 0.0),
                    protein_g=snapshot.get("protein", 0.0),
                    meal_slot=slot,
                    bg_mgdl=old_rec.glucose.mgdl,
                    target_mgdl=user_settings.targets.mid
                )
                
                new_rec = calculate_bolus_v2(
                    request=req_v2,
                    settings=user_settings,
                    iob_u=old_rec.iob_u,
                    glucose_info=old_rec.glucose
                )
                
                # Update Snapshot
                snapshot["rec"] = new_rec
                
                # Update Message
                rec_u = new_rec.total_u_final
                lines = []
                lines.append(f"🍽️ **Nueva Comida Detectada** (MFP)")
                lines.append(f"Slot: **{slot.upper()}**")
                lines.append("")
                lines.append(f"Resultado: **{rec_u} U**")
                lines.append("")
                if new_rec.explain:
                    for ex in new_rec.explain:
                        lines.append(f"• {ex}")
                lines.append("")
                lines.append(f"Redondeo final: {new_rec.total_u_raw:.2f} → {new_rec.total_u_final} U")
                lines.append("")
                lines.append(f"¿Registrar {rec_u} U?")
                
                msg_text = "\n".join(lines)
                
                keyboard = [
                    [
                        InlineKeyboardButton(f"✅ Poner {rec_u} U", callback_data=f"accept|{req_id}"),
                        InlineKeyboardButton("✏️ Cantidad", callback_data=f"edit_dose|{rec_u}|{req_id}"),
                        InlineKeyboardButton("❌ Ignorar", callback_data=f"cancel|{req_id}")
                    ],
                    [
                        InlineKeyboardButton("🌅 Desayuno", callback_data=f"set_slot|breakfast|{req_id}"),
                        InlineKeyboardButton("🍕 Comida", callback_data=f"set_slot|lunch|{req_id}"),
                        InlineKeyboardButton("🍽️ Cena", callback_data=f"set_slot|dinner|{req_id}"),
                        InlineKeyboardButton("🥨 Snack", callback_data=f"set_slot|snack|{req_id}"),
                    ]
                ]
                await edit_message_text_safe(query, text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                await query.answer(f"Slot cambiado a {slot}")
                health.record_action(f"callback:set_slot:{slot}", True)
            except Exception as e:
                logger.error(f"SetSlot callback error: {e}")
                await query.answer("Error al cambiar slot")
            return

        # Accept
        await _handle_snapshot_callback(query, data)
        return

    # --- 1.5 Vision / Manual Calc Flow ---
    if data.startswith("chat_bolus_edit_"):
        try:
            carbs_val = float(data.split("_")[-1])
            await _handle_add_treatment_tool(update, context, {"carbs": carbs_val})
            health.record_action("vision_calc", True)
        except Exception as e:
            logger.error(f"Vision calc error: {e}")
            await edit_message_text_safe(query, text=f"❌ Error: {e}")
        return

    # --- 2. Voice Flow ---
    if data.startswith("voice_confirm_"):
        await _handle_voice_callback(update, context) # Refactored or inline
        return
        
    # --- 3. Combo Followup ---
    if data.startswith("combo_"):
        # combo_yes|tid, combo_later|tid, combo_no|tid
        parts = data.split("|")
        action = parts[0]
        tid = parts[1] if len(parts) > 1 else "unknown"
        
        if action == "combo_yes":
             # Trigger logic to add remaining part? 
             # For now, just prompt user or log. User asked to "Registrar 2a parte".
             # We assume manual entry or simplified addition.
             await edit_message_text_safe(query, "✅ Anotado. (Funcionalidad completa en vNext)")
             health.record_action(f"callback:combo_yes:{tid}", True)
             
        elif action == "combo_later":
             # Snooze
             await edit_message_text_safe(query, "⏳ Pospuesto 30 min.")
             health.record_action(f"callback:combo_later:{tid}", True)
             
        elif action == "combo_no":
             await edit_message_text_safe(query, "❌ Descartado.")
             health.record_action(f"callback:combo_no:{tid}", True)
             health.record_action(f"callback:combo_no:{tid}", True)
        return

    # --- 3.5 Rename / Fav Flow ---
    if data.startswith("rename_txn|"):
         tid = data.split("|")[1]
         context.user_data["renaming_treatment_id"] = tid
         await edit_message_text_safe(query, f"{query.message.text}\n\n✏️ **Escribe el nuevo nombre/nota para el historial:**")
         return

    if data.startswith("save_fav_txn|"):
         tid = data.split("|")[1]
         context.user_data["saving_favorite_tid"] = tid
         await edit_message_text_safe(query, f"{query.message.text}\n\n⭐ **Escribe el nombre para guardar en Mis Platos:**")
         return

    # --- 4. Basal Interactive Flow ---
    if data == "basal_later":
        # Snooze 15m
        await _update_basal_event("snoozed", snooze_minutes=15)
        health.record_action("action_basal_snoozed", True, "15m")
        await edit_message_text_safe(query, f"{query.message.text}\n\n⏳ Te avisaré en 15 minutos.")
        return

    if data == "basal_no":
         await _update_basal_event("dismissed")
         health.record_action("action_basal_dismissed_today", True)
         await edit_message_text_safe(query, f"{query.message.text}\n\n❌ Oído cocina. Hoy no pregunto más.")
         return
    
    if data == "basal_cancel":
         # Just cancel interaction, keep "asked" state or revert? 
         # User says "cancel" maybe means "don't do now". treated same as "asked" but message closed.
         health.record_action("action_basal_cancelled", True)
         await edit_message_text_safe(query, f"{query.message.text}\n\n❌ Cancelado.")
         return

    if data == "basal_yes":
         # Start Registration Logic
         try:
             user_settings = await get_bot_user_settings()
             basal_conf = user_settings.bot.proactive.basal
             
             # Calculate Lateness
             now_loc = datetime.now() 
             hours_late = 0.0
             target_str = basal_conf.time_local
             
             if target_str:
                 try:
                     t_target = datetime.strptime(target_str, "%H:%M").time()
                     d_target = datetime.combine(now_loc.date(), t_target)
                     diff = (now_loc - d_target).total_seconds() / 3600.0
                     if diff > 0: hours_late = diff
                 except: pass
                 
             suggested_u = basal_conf.expected_units or 0.0
             
             msg_text = ""
             
             if hours_late > 1.0: # Only if significant delay
                  from app.services.basal_engine import calculate_late_basal
                  suggested_late = calculate_late_basal(hours_late, suggested_u)
                  msg_text = (
                      f"⚠️ **Vas tarde ({hours_late:.1f}h)**\n"
                      f"Dosis habitual: {suggested_u} U\n"
                      f"Sugerencia ajustada: **{suggested_late} U**\n\n"
                      f"¿Qué quieres registrar?"
                  )
                  suggested_u = suggested_late # Default to late calc
             else:
                  msg_text = f"✅ **Registrar Basal**\nDosis habitual: **{suggested_u} U**. ¿Confirmas?"
             
             # Buttons
             kb = [
                 [InlineKeyboardButton(f"✅ Confirmar {suggested_u} U", callback_data=f"basal_confirm|{suggested_u}")],
                 [InlineKeyboardButton("✏️ Editar", callback_data="basal_edit")],
                 [InlineKeyboardButton("❌ Cancelar", callback_data="basal_cancel")]
             ]
             await edit_message_text_safe(query, text=msg_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
             health.record_action("action_basal_register_start", True)
             
         except Exception as e:
             logger.error(f"Basal yes error: {e}")
             await edit_message_text_safe(query, "Error interno.")
         return

    if data.startswith("basal_confirm|"):
         try:
             units = float(data.split("|")[1])
             
             # --- SAFETY RAIL: Check if already added recently ---
             # (Prevents race condition where user adds manually while bot is waiting)
             try:
                 user_settings = await get_bot_user_settings()
                 username = user_settings.username or "admin" # Default
                 last_basal, mins_ago = await get_latest_basal_dose(username)
                 
                 # If we found a basal injected in the last 20 hours, we might want to be careful.
                 # But specifically for the "Race Condition", we care about VERY recent.
                 # However, if user already logged "Basal" today, we should block.
                 # Let's say: if logged < 12h ago, Assume it's the daily dose.
                 if last_basal and mins_ago < 720: # 12 hours
                     # It's highly likely they already put it
                     logger.warning(f"Guardrail blocked basal: Found one {mins_ago}m ago")
                     await _update_basal_event("done") # Mark as done so we don't ask again
                     health.record_action("basal_guardrail_block", True, f"found_recent_{mins_ago}m")
                     await edit_message_text_safe(query, f"{query.message.text}\n\n⚠️ **Ya registrada**\nHe visto una basal reciente ({int(mins_ago)} min). No la duplico.")
                     return
             except Exception as e:
                 logger.error(f"Basal guardrail check failed: {e}")
                 # Fail safe? Or proceed? Proceeding is risky. Let's warn but proceed if DB error?
                 # Safest is to proceed if we can't verify, BUT log heavily. 
                 # Or better: if checking fails, we shouldn't block user from living.
                 pass

             # Add Treatment
             add_res = await tools.add_treatment({
                 "insulin": units,
                 "carbs": 0,
                 "notes": "Basal (Bot Reminder)",
                 "event_type": "Basal"
             })

             
             if isinstance(add_res, tools.ToolError):
                 raise Exception(add_res.message)
                 
             # Mark Done
             await _update_basal_event("done")
             health.record_action("action_basal_register_done", True, f"units={units}")
             
             success_txt = f"{query.message.text}\n\n✅ Registrada: **{units} U**"
             
             if getattr(add_res, "injection_site", None):
                 site = add_res.injection_site
                 success_txt += f"\n📍 Rotado: {site['name']} {site['emoji']}"
                 
                 # Send Image Logic (Basal)
                 if site.get("image"):
                     try:
                         from app.bot.image_renderer import generate_injection_image
                         base_dir = Path(__file__).parent.parent / "static" / "assets"
                         site_id = site.get("id")
                         img_bytes = None
                         
                         if site_id:
                             try:
                                 img_bytes = generate_injection_image(site_id, base_dir)
                             except Exception as gen_e:
                                 logger.error(f"Image generation error (Basal): {gen_e}")

                         if img_bytes:
                             logger.info(f"Sending generated injection image for Basal {site_id}")
                             # Force unique filename to prevent caching
                             safe_label = site['name'][:20].replace(" ", "_").replace(".", "").encode('ascii', 'ignore').decode('ascii')
                             img_bytes.name = f"inj_basal_{safe_label}_{uuid.uuid4().hex[:6]}.png"
                             
                             await context.bot.send_photo(chat_id=query.effective_chat.id, photo=img_bytes)
                         else:
                             # Fallback Static
                             img_path = base_dir / site["image"]
                             if img_path.exists():
                                 await context.bot.send_photo(chat_id=query.effective_chat.id, photo=open(img_path, "rb"))
                     except Exception as e:
                         logger.error(f"Failed to send basal injection image: {e}")

             await edit_message_text_safe(query, success_txt, parse_mode="Markdown")
             
         except Exception as e:
             health.record_action("action_basal_register_done", False, str(e))
             await edit_message_text_safe(query, f"❌ Error al registrar: {e}")
         return

    if data == "basal_edit":
         context.user_data["editing_basal"] = True
         await edit_message_text_safe(query, f"{query.message.text}\n\n✏️ **Escribe la cantidad de unidades:**")
         return

async def _handle_voice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles voice confirmation callbacks."""
    query = update.callback_query
    data = query.data
    
    # data: "voice_confirm_yes", "voice_confirm_retry", "voice_confirm_cancel"
    action = data.replace("voice_confirm_", "")
    
    pending_text = context.user_data.get("pending_voice_text")
    
    if action == "cancel":
        context.user_data.pop("pending_voice_text", None)
        await edit_message_text_safe(query, "❌ Nota de voz descartada.")
        return

    if action == "retry":
        context.user_data.pop("pending_voice_text", None)
        await edit_message_text_safe(query, "🔄 Vale, descarte. Envía otra nota de voz o escribe.")
        return

    if action == "yes":
        if not pending_text:
             await edit_message_text_safe(query, "⚠️ Error: Texto perdido. Por favor repite.")
             return
             
        # Simulate text message
        await edit_message_text_safe(query, f"🗣️ Procesando: \"{pending_text}\"...")
        
        # We need to call handle_message, but update.message might be None or pointing to the button click?
        # We can't easily fake the update object fully without side effects.
        # Better: Create a mock update or extract the logic of handle_message that processes text.
        # But handle_message takes Update.
        # Let's try to mutate the update to look like a message update.
        # Or better: Extract logic. But for now, let's try calling handle_message by faking specific attributes if possible.
        # Actually, since handle_message reads update.message.text, we can't easily use the callback update.
        
        # Alternative: We can execute the logic directly if it's simple command routing, 
        # but handle_message does AI routing.
        
        # Let's try to construct a minimal Update/Message object?
        # That's risky.
        
        # Simplest valid approach: Send a real message from the user? No API for that.
        # We process it as if it passed the check.
        # Reuse router logic directly?
        
        # For this fix, let's call the AI Router manually, similar to handle_message.
        # This is duplication but safer than faking Update.
        
        try:
            user_username = update.effective_user.username
            chat_id = update.effective_chat.id
            
            # Show typing
            await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
            
            # Build Context
            ctx = await context_builder.build_context(user_username, chat_id)
            
            # Router
            bot_reply = await router.handle_text(user_username, chat_id, pending_text, ctx)
            
            # Reply
            if bot_reply.pending_action:
                p = bot_reply.pending_action
                p["timestamp"] = datetime.now().timestamp()
                SNAPSHOT_STORAGE[p["id"]] = p
            
            if bot_reply.buttons:
                reply_markup = InlineKeyboardMarkup(bot_reply.buttons)
                await reply_text(update, context, bot_reply.text, reply_markup=reply_markup)
            else:
                await reply_text(update, context, bot_reply.text)
                
            context.user_data.pop("pending_voice_text", None)
            
        except Exception as e:
            logger.error(f"Voice confirm processing error: {e}")
            await reply_text(update, context, f"Error procesando voz: {e}")
