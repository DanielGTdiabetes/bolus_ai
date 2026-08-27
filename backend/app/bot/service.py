import logging
import asyncio
import os
import tempfile
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse, urlunparse
import uuid
import time


from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Conflict, Forbidden, InvalidToken, NetworkError, RetryAfter, TimedOut
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from telegram import constants

from app.core import config
from app.bot import ai
from app.bot import tools
from app.bot import voice
from app.bot.state import health, BotMode
from app.bot.leader_lock import build_instance_id, release_bot_leader, try_acquire_bot_leader
from app.bot import proactive
from app.bot import context_builder
from app.bot.llm import router
from app.bot.image_renderer import generate_injection_image
from app.bot.context_vars import bot_user_context
from app.core.db import get_session_factory

# Sidecar dependencies
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.services.dexcom_client import DexcomClient
from app.services.iob import compute_iob_from_sources, compute_cob_from_sources
from app.bot.bolus_client import calculate_bolus_for_bot
from app.services.basal_repo import get_latest_basal_dose, upsert_basal_dose
from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2
from app.bot.capabilities.registry import build_registry, Permission
from app.bot.snapshot_store import SnapshotStore
from app.bot.bolus_snapshot import build_slot_recalc_payload
from app.services.bolus_trace import build_bolus_trace

_snapshot_store: Optional[SnapshotStore] = None

def _get_snapshot_store() -> SnapshotStore:
    global _snapshot_store
    if _snapshot_store is None:
        data_dir = Path(get_settings().data.data_dir)
        _snapshot_store = SnapshotStore(data_dir)
    return _snapshot_store

EXERCISE_FLOW_TTL_SECONDS = 15 * 60
EXERCISE_LEVEL_LABELS = {
    "low": "Suave",
    "moderate": "Moderado",
    "high": "Intenso",
}
EXERCISE_DURATION_PRESETS = [15, 30, 45, 60]


def _exercise_flow_expired(flow: dict) -> bool:
    created_at = flow.get("created_at", 0)
    return (time.time() - created_at) > EXERCISE_FLOW_TTL_SECONDS



def _format_exercise_label(intensity: str) -> str:
    return EXERCISE_LEVEL_LABELS.get(intensity, intensity)


def _escape_md_v1(text: str) -> str:
    """Escapes markdown v1 special characters to prevent API errors."""
    if not text:
        return ""
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")


def _resolve_bolus_delivery(rec: BolusResponseV2) -> tuple[float, float, float, int]:
    total = max(0.0, float(getattr(rec, "total_u_final", 0) or 0))
    later = max(0.0, float(getattr(rec, "later_u", 0) or 0))
    is_dual = getattr(rec, "kind", "normal") in ("dual", "extended") and later > 0
    if not is_dual:
        return total, total, 0.0, 0

    upfront = max(0.0, float(getattr(rec, "upfront_u", total - later) or 0))
    return total, upfront, later, max(0, int(getattr(rec, "duration_min", 0) or 0))


def _snapshot_glucose_mgdl(snapshot: dict) -> Optional[float]:
    candidates = []
    rec = snapshot.get("rec")
    rec_glucose = getattr(rec, "glucose", None)
    candidates.append(getattr(rec_glucose, "mgdl", None))

    payload = snapshot.get("payload")
    if isinstance(payload, dict):
        candidates.extend([payload.get("bg_mgdl"), payload.get("glucose")])
    elif payload is not None:
        candidates.append(getattr(payload, "bg_mgdl", None))
    candidates.extend([snapshot.get("bg"), snapshot.get("glucose")])

    for value in candidates:
        try:
            glucose = float(value)
        except (TypeError, ValueError):
            continue
        if 1 <= glucose <= 400:
            return glucose
    return None


def _meal_episode_origin_id(
    origin_id: Optional[str], meal_revision: Optional[str]
) -> Optional[str]:
    if not origin_id:
        return None
    if not meal_revision:
        return origin_id
    return f"{origin_id}:{meal_revision}"


def _build_bot_active_plan(
    rec: BolusResponseV2,
    *,
    treatment_id: Optional[str],
    accepted_upfront_u: float,
    snapshot: dict,
    later_u_override: Optional[float] = None,
    duration_min_override: Optional[int] = None,
) -> Optional[dict]:
    total, _, rec_later, rec_duration = _resolve_bolus_delivery(rec)
    later = rec_later if later_u_override is None else max(0.0, later_u_override)
    duration = rec_duration if duration_min_override is None else max(0, duration_min_override)
    if not treatment_id or later <= 0:
        return None

    payload = snapshot.get("payload")
    meal_slot = getattr(payload, "meal_slot", None)
    created_at_ts = int(time.time() * 1000)
    return {
        "id": treatment_id,
        "plan_id": treatment_id,
        "treatment_id": treatment_id,
        "created_at_ts": created_at_ts,
        "upfront_u": max(0.0, float(accepted_upfront_u)),
        "later_u_planned": later,
        "later_after_min": duration,
        "extended_duration_min": duration or None,
        "mode": "dual",
        "source": "telegram-engine-split",
        "meal_slot": meal_slot,
        "total_recommended_u": total,
        "status": "pending",
        "notes": f"Origen: Telegram ({snapshot.get('source') or 'bolus'})",
    }


def _persist_bot_active_plan(store: DataStore, plan: dict) -> None:
    from app.services.active_plan_store import load_active_plans, save_active_plans

    plans = [existing for existing in load_active_plans(store) if existing.get("id") != plan["id"]]
    plans.append(plan)
    save_active_plans(store, plans)



def _build_bolus_message(
    rec: BolusResponseV2,
    *,
    carbs: float,
    fat: float,
    protein: float,
    bg_val: Optional[float],
    request_id: str,
    notes: str,
    exercise_summary: Optional[str] = None,
) -> tuple[str, bool, str]:
    total_u, upfront_u, later_u, duration_min = _resolve_bolus_delivery(rec)
    lines = [f"Sugerencia total: **{total_u:g} U**"]

    if later_u > 0:
        lines.append(f"- Dosis inmediata: **{upfront_u:g} U**")
        lines.append(
            f"- Planificada para revisar más tarde: **{later_u:g} U** "
            f"(tras {duration_min} min)"
        )

    if carbs > 0:
        lines.append(f"- Carbos: {carbs}g → {rec.meal_bolus_u:.2f} U")
    else:
        lines.append("- Carbos: 0g")

    targ_val = rec.used_params.target_mgdl
    if rec.correction_u != 0:
        sign = "+" if rec.correction_u > 0 else ""
        if bg_val is not None:
            lines.append(
                f"- Corrección: {sign}{rec.correction_u:.2f} U ({bg_val:.0f} → {targ_val:.0f})"
            )
        else:
            lines.append(f"- Corrección: {sign}{rec.correction_u:.2f} U")
    elif bg_val is not None:
        lines.append(f"- Corrección: 0.0 U ({bg_val:.0f} → {targ_val:.0f})")
    else:
        lines.append("- Corrección: 0.0 U (Falta Glucosa)")

    positive_correction = max(rec.correction_u, 0.0)
    iob_applied = min(positive_correction, max(rec.iob_u, 0.0))
    correction_remaining = max(positive_correction - iob_applied, 0.0)
    if rec.iob_u > 0:
        lines.append(
            f"- IOB activo: {rec.iob_u:.2f} U "
            f"(aplicado a corrección: {iob_applied:.2f} U; "
            f"corrección restante: {correction_remaining:.2f} U)"
        )
    else:
        lines.append("- IOB activo: 0.00 U")

    if exercise_summary:
        lines.append(f"🏃 Ejercicio: {exercise_summary}")

    lines.append(f"(`{request_id}`)")

    fiber_msg = next(
        (x for x in rec.explain if "Fibra" in x or "Restando" in x),
        None,
    )
    if fiber_msg:
        lines.append(f"ℹ️ {fiber_msg}")
        notes += f" [{fiber_msg}]"

    fiber_dual_rec = any("Valorar Bolo Dual" in x for x in rec.explain)
    if not fiber_dual_rec and (fat > 0 or protein > 0):
        lines.append(f"🥩 Macros extra: F:{fat} P:{protein}")

    return "\n".join(lines), fiber_dual_rec, notes


def _keyboard_button_texts(keyboard: list[list[InlineKeyboardButton]]) -> list[list[str]]:
    return [[button.text for button in row] for row in keyboard]


def _log_bolus_keyboard_build(
    update: Optional[Update],
    *,
    request_id: str,
    bolus_mode: str,
    keyboard: list[list[InlineKeyboardButton]],
) -> None:
    user_id = getattr(update.effective_user, "id", None) if update else None
    chat_id = getattr(update.effective_chat, "id", None) if update else None
    has_bolus_context = request_id in _get_snapshot_store()
    buttons = _keyboard_button_texts(keyboard)
    logger.info(
        "bot_bolus_keyboard_build start: user_id=%s chat_id=%s has_bolus_context=%s bolus_mode=%s buttons=%s",
        user_id,
        chat_id,
        has_bolus_context,
        bolus_mode,
        buttons,
    )


def _maybe_append_exercise_button(
    keyboard: list[list[InlineKeyboardButton]],
    *,
    request_id: str,
    label: str,
) -> None:
    if request_id:
        logger.info("bot_exercise_button gate: reason=shown motive=request_id_present")
        keyboard.append([
            InlineKeyboardButton(label, callback_data=f"exercise_start|{request_id}")
        ])
    else:
        logger.info("bot_exercise_button gate: reason=hidden motive=missing_request_id")


def _build_bolus_recommendation_keyboard(
    update: Optional[Update],
    *,
    request_id: str,
    rec_u: float,
    user_settings: Any,
    fiber_dual_rec: bool,
    exercise_label: str = "🏃 Añadir ejercicio",
) -> list[list[InlineKeyboardButton]]:
    row1 = [
        InlineKeyboardButton(f"✅ Poner {rec_u} U", callback_data=f"accept|{request_id}"),
        InlineKeyboardButton("✏️ Cantidad", callback_data=f"edit_dose|{rec_u}|{request_id}"),
        InlineKeyboardButton("❌ Ignorar", callback_data=f"cancel|{request_id}"),
    ]

    keyboard = [row1]

    if fiber_dual_rec:
        split_pct = 70
        later_after_min = 120
        if user_settings.dual_bolus:
            split_pct = user_settings.dual_bolus.percent_now
            later_after_min = user_settings.dual_bolus.later_after_minutes
            if split_pct < 10:
                split_pct = 10
            if split_pct > 90:
                split_pct = 90

        fraction = split_pct / 100.0
        total = rec_u
        now_u = round(total * fraction, 2)
        later_u = round(total * (1.0 - fraction), 2)

        keyboard.insert(1, [
            InlineKeyboardButton(
                f"✅ Dual ({split_pct}/{100 - split_pct}) -> {now_u} + {later_u}e",
                callback_data=f"accept_dual|{request_id}|{now_u}|{later_u}|{later_after_min}",
            )
        ])

    _maybe_append_exercise_button(keyboard, request_id=request_id, label=exercise_label)

    keyboard.append([
        InlineKeyboardButton("🌅 Desayuno", callback_data=f"set_slot|breakfast|{request_id}"),
        InlineKeyboardButton("🍕 Comida", callback_data=f"set_slot|lunch|{request_id}"),
        InlineKeyboardButton("🍽️ Cena", callback_data=f"set_slot|dinner|{request_id}"),
        InlineKeyboardButton("🥨 Snack", callback_data=f"set_slot|snack|{request_id}"),
    ])

    _log_bolus_keyboard_build(
        update,
        request_id=request_id,
        bolus_mode="dual" if fiber_dual_rec else "simple",
        keyboard=keyboard,
    )

    return keyboard


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
_leader_task: Optional[asyncio.Task] = None
_leader_instance_id: Optional[str] = None


async def notify_admin(text: str) -> bool:
    """Sends a message to the configured admin user."""
    admin_id = config.get_allowed_telegram_user_id()
    if not admin_id:
        logger.warning("notify_admin failed: No admin ID configured")
        return False
    
    # We call bot_send directly.
    # Note: bot_send uses _bot_app global.
    res = await bot_send(chat_id=admin_id, text=text, log_context="notify_admin")
    return res is not None

async def bot_send(
    chat_id: int,
    text: str,
    *,
    bot=None,
    log_context: str = "reply",
    raise_on_error: bool = False,
    **kwargs: Any,
) -> Optional[Any]:
    """Centralized sender for Telegram replies with health tracking."""
    logger.info("sending reply", extra={"chat_id": chat_id, "context": log_context})

    target_bot = bot or (_bot_app.bot if _bot_app else None)
    if not target_bot:
        error_msg = "bot_unavailable"
        logger.error(f"reply failed: {error_msg}")
        health.set_reply_error(error_msg)
        if raise_on_error:
            raise RuntimeError(error_msg)
        return None

    try:
        result = await target_bot.send_message(chat_id=chat_id, text=text, **kwargs)
        health.mark_reply_success()
        logger.info(
            "reply ok",
            extra={
                "chat_id": chat_id,
                "context": log_context,
                "message_id": getattr(result, "message_id", None),
            },
        )
        return result
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error(f"reply failed: {error_msg}")
        health.set_reply_error(error_msg)
        if raise_on_error:
            raise
        return None


async def edit_message_text_safe(editor, *args: Any, **kwargs: Any) -> Optional[Any]:
    try:
        return await editor.edit_message_text(*args, **kwargs)
    except BadRequest as exc:
        err_str = str(exc)
        err_lower = err_str.lower()
        
        if "message is not modified" in err_lower:
            logger.info("edit_message_not_modified", extra={"context": kwargs.get("context")})
            return None
            
        # Robust Fallback: If Markdown fails, strip mode and retry as plain text.
        # Common errors: "Can't parse entities", "Unmatched", "Byte offset"
        if "parse entities" in err_lower or "byte offset" in err_lower or "cant parse" in err_lower or "can't parse" in err_lower:
            logger.warning(f"Markdown parse failed ({err_str}). Retrying as Plain Text.")
            kwargs.pop("parse_mode", None) 
            # Note: We keep the text as-is (with * and _), they will just appear literally.
            try:
                return await editor.edit_message_text(*args, **kwargs)
            except Exception as retry_exc:
                # FINAL SAFETY NET: Never crash the bot flow due to a view update error.
                # Just log it and pretend it worked (or ignored).
                text_preview = kwargs.get("text", "")[:50]
                logger.error(f"Fallback plain text edit also failed: {retry_exc} | text_start='{text_preview}'")
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
    
    # HYBRID ARCHITECTURE LOGIC:
    # 1. Detect Environment
    is_render = os.environ.get("RENDER") is not None
    settings = get_settings()

    # 2. Render (Cloud) Behavior
    if is_render:
        # If Cloud is in Standby (Emergency Mode OFF), it must NOT register webhook.
        # It stays in "Send Only" mode to allow outgoing alerts but no incoming.
        if not settings.emergency_mode:
             return BotMode.DISABLED, "emergency_mode_send_only"
        
        # If Emergency Mode ON, it becomes the Active bot (Webhook)
        if public_url:
             return BotMode.WEBHOOK, "cloud_emergency_active"
        else:
             return BotMode.POLLING, "cloud_emergency_no_url"

    # 3. NAS (On-Prem) Behavior
    # NAS always runs logic via Polling (unless disabled explicitly).
    # It ignores public_url presence because that URL points to Cloud/Nginx, not directly to NAS usually.
    return BotMode.POLLING, "forced_polling_on_prem"


def build_expected_webhook() -> Tuple[Optional[str], str]:
    """
    Returns (expected_url, source_env_key)
    """
    public_url, source = config.get_public_bot_url_with_source()
    if not public_url:
        return None, source
    return f"{public_url}/api/webhook/telegram", source


async def _acquire_leader_lock(mode: BotMode, reason: str) -> Tuple[BotMode, str, bool]:
    if mode == BotMode.DISABLED:
        return mode, reason, False

    session_factory = get_session_factory()
    if not session_factory:
        logger.warning("bot_leader_lock skipped: no database session factory available")
        return mode, reason, True

    instance_id = build_instance_id()
    ttl_seconds = config.get_bot_leader_ttl_seconds()
    renew_seconds = config.get_bot_leader_renew_seconds()
    if renew_seconds >= ttl_seconds:
        renew_seconds = max(1, ttl_seconds // 2)

    async with session_factory() as session:
        is_leader, info = await try_acquire_bot_leader(session, instance_id, ttl_seconds)

    logger.info(
        "bot_leader_lock ingest_id=%s action=%s owner=%s ttl=%s expires_at=%s",
        instance_id,
        info.get("action"),
        info.get("owner_id"),
        ttl_seconds,
        info.get("expires_at"),
    )

    if not is_leader:
        logger.warning(
            "bot_leader_lock_standby owner=%s expires_at=%s",
            info.get("owner_id"),
            info.get("expires_at"),
        )
        return BotMode.DISABLED, "leader_lock_standby", False

    global _leader_task, _leader_instance_id
    _leader_instance_id = instance_id

    async def _leader_heartbeat() -> None:
        while True:
            try:
                await asyncio.sleep(renew_seconds)
                async with session_factory() as session:
                    renewed, renew_info = await try_acquire_bot_leader(
                        session,
                        instance_id,
                        ttl_seconds,
                    )
                if not renewed:
                    logger.warning(
                        "bot_leader_lock_lost owner=%s expires_at=%s",
                        renew_info.get("owner_id"),
                        renew_info.get("expires_at"),
                    )
                    health.set_mode(BotMode.DISABLED, "leader_lock_lost")
                    await shutdown()
                    return
                logger.info(
                    "bot_leader_lock_renewed action=%s owner=%s expires_at=%s",
                    renew_info.get("action"),
                    renew_info.get("owner_id"),
                    renew_info.get("expires_at"),
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("bot_leader_lock_renew_failed: %s", exc)
                await asyncio.sleep(renew_seconds)

    _leader_task = asyncio.create_task(_leader_heartbeat(), name="bot_leader_heartbeat")
    return mode, reason, True
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    error_id = uuid.uuid4().hex[:8]
    
    # Auto-Healing for Conflict (Webhook collisions)
    if isinstance(context.error, Conflict):
        logger.warning(f"⚠️ Conflict Error detected (Webhooks?): {context.error}. Attempting auto-healing...")
        try:
             await context.bot.delete_webhook(drop_pending_updates=False)
             logger.info("✅ Auto-healing: Webhook deleted successfully via error_handler.")
        except Exception as heal_err:
             logger.error(f"❌ Auto-healing failed: {heal_err}")

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

async def get_bot_user_settings_with_user_id(
    username: Optional[str] = None,
) -> tuple[UserSettings, str]:
    """
    Helper to fetch settings + resolved user_id.
    Defaults to resolver priority (preferred -> BOT_DEFAULT_USERNAME -> freshest non-default).
    """
    resolved_settings, resolved_user = await resolve_bot_user_settings(username)
    logger.info("Bot using settings for user_id='%s'", resolved_user)
    return resolved_settings, resolved_user


async def get_bot_user_settings(username: Optional[str] = None) -> UserSettings:
    settings, _ = await get_bot_user_settings_with_user_id(username)
    return settings


def _resolve_bolus_user_id(user_settings: UserSettings, resolved_user_id: Optional[str]) -> str:
    bolus_user_id = resolved_user_id or getattr(user_settings, "user_id", None)
    if not bolus_user_id:
        logger.info("bot_bolus_user_fallback: using user_id='admin'")
        bolus_user_id = "admin"
    return bolus_user_id


async def _calculate_bolus_with_context(
    req_v2: BolusRequestV2,
    *,
    user_settings: UserSettings,
    resolved_user_id: Optional[str],
    snapshot_user_id: Optional[str] = None,
) -> BolusResponseV2:
    bolus_user_id = _resolve_bolus_user_id(
        user_settings,
        snapshot_user_id or resolved_user_id,
    )
    return await calculate_bolus_for_bot(req_v2, username=bolus_user_id)


async def _hydrate_bolus_snapshot(
    pending_action: dict,
) -> dict:
    if pending_action.get("type") != "bolus":
        return pending_action
    if "payload" in pending_action and "user_id" in pending_action:
        return pending_action

    user_settings, resolved_user_id = await get_bot_user_settings_with_user_id()
    carbs = float(pending_action.get("carbs", 0) or 0)
    pending_action.setdefault("user_id", resolved_user_id)
    pending_action.setdefault(
        "payload",
        BolusRequestV2(
            carbs_g=carbs,
            meal_slot=get_current_meal_slot(user_settings),
            confirm_iob_unknown=True,
            confirm_iob_stale=True,
        ),
    )
    pending_action.setdefault("rec", None)
    return pending_action

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
             # Determine Context: Next vs Last
             is_next_tool = (name == "get_injection_site")
             
             next_name = res.name if is_next_tool else getattr(res, "secondary_name", "???")
             last_name = getattr(res, "secondary_name", "Ninguno") if is_next_tool else res.name
             
             text = (
                 f"📍 **Rotación de Inyección**\n"
                 f"🟢 **Toca:** {next_name}\n"
                 f"🔴 **Anterior:** {last_name}"
             )

             # Send Image if available
             target_id = getattr(res, "id", None)
             sec_id = getattr(res, "secondary_id", None)
             
             if target_id:
                 try:
                     assets = Path(get_settings().data.static_dir or "app/static") / "assets"
                     if not assets.exists():
                         assets = Path(os.getcwd()) / "app" / "static" / "assets"
                     
                     # Determine Mode and Arguments based on Renderer expectations (Primary=Green/Next, Secondary=Red/Last)
                     # If combined, we want mode 'next_last_combined'
                     is_combined = bool(sec_id)
                     mode = "next_last_combined" if is_combined else ("recommended" if is_next_tool else "last")
                     
                     # Map IDs to Renderer (Primary=Next, Secondary=Last)
                     # get_injection_site returns id=Next, sec=Last. NO SWAP needed.
                     # get_last_injection_site returns id=Last, sec=Next. SWAP needed.
                     
                     p_id = target_id
                     s_id = sec_id
                     if not is_next_tool and is_combined:
                         p_id = sec_id
                         s_id = target_id
                     
                     img_bytes = generate_injection_image(p_id, assets, mode=mode, secondary_site_id=s_id)
                     if img_bytes:
                         await context.bot.send_photo(chat_id=update.effective_chat.id, photo=img_bytes)
                 except Exception as img_err:
                     logger.error(f"Failed to send injection image ({target_id}): {img_err}", exc_info=True)

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

    imported_edit = context.user_data.get("imported_meal_edit")
    if imported_edit:
        from app.services.imported_meal_service import add_food, edit_food
        from app.models.imported_meal import ImportedMeal

        step = imported_edit.get("step")
        meal_id = imported_edit.get("meal_id")
        try:
            if step == "add_name":
                if not text.strip():
                    raise ValueError("Escribe un nombre")
                imported_edit["name"] = text.strip()
                imported_edit["step"] = "add_carbs"
                context.user_data["imported_meal_edit"] = imported_edit
                await reply_text(update, context, f"HC para {text.strip()} (en gramos):")
                return
            if step in {"carbs", "add_carbs"}:
                value = float(text.replace(",", "."))
                if value < 0 or value > 500:
                    raise ValueError("Los HC deben estar entre 0 y 500 g")
                async with SessionLocal() as session:
                    if step == "carbs":
                        meal = await edit_food(session, meal_id=meal_id, index=int(imported_edit["index"]), carbs=value)
                    else:
                        meal = await add_food(session, meal_id=meal_id, name=imported_edit["name"], carbs=value)
                    await _sync_imported_meal_draft(session, meal)
                    await session.commit()
                    await _edit_imported_meal_card(context.bot, update.effective_chat.id, meal)
                context.user_data.pop("imported_meal_edit", None)
                await reply_text(update, context, f"✅ Comida actualizada. Total actual: {meal.calculated_carbs:g} g HC")
                return
            if step == "quantity":
                async with SessionLocal() as session:
                    meal = await edit_food(session, meal_id=meal_id, index=int(imported_edit["index"]), quantity=text)
                    await _sync_imported_meal_draft(session, meal)
                    await session.commit()
                    await _edit_imported_meal_card(context.bot, update.effective_chat.id, meal)
                context.user_data.pop("imported_meal_edit", None)
                await reply_text(update, context, "✅ Cantidad actualizada.")
                return
            context.user_data.pop("imported_meal_edit", None)
        except (TypeError, ValueError) as exc:
            await reply_text(update, context, f"⚠️ {exc}. Inténtalo de nuevo o pulsa Volver.")
            return

    exercise_flow = context.user_data.get("exercise_flow")
    if exercise_flow and exercise_flow.get("step") == "awaiting_duration":
        if _exercise_flow_expired(exercise_flow):
            context.user_data.pop("exercise_flow", None)
            await reply_text(update, context, "⏱️ Sesión de ejercicio caducada. Vuelve a intentarlo.")
            return
        try:
            minutes_val = int(float(text.replace(",", ".")))
            if minutes_val <= 0:
                raise ValueError("Minutes must be positive")
        except ValueError:
            await reply_text(update, context, "⚠️ Indica los minutos (ej. 25).")
            return

        intensity = exercise_flow.get("level")
        req_id = exercise_flow.get("request_id")
        context.user_data["exercise_flow"]["step"] = "calculating"
        await _apply_exercise_recalculation(
            update,
            context,
            request_id=req_id,
            intensity=intensity,
            minutes=minutes_val,
            source="manual",
        )
        context.user_data.pop("exercise_flow", None)
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

    # 0. Intercept Macro Edit (C F P)
    editing_meal_id = context.user_data.get("editing_meal_request")
    if editing_meal_id:
        try:
            parts = text.replace(",", ".").split()
            if len(parts) < 1:
                raise ValueError("Empty")
            
            c_val = float(parts[0])
            f_val = float(parts[1]) if len(parts) > 1 else 0.0
            p_val = float(parts[2]) if len(parts) > 2 else 0.0
            
            del context.user_data["editing_meal_request"]
            
            # Update Snapshot
            req_id = editing_meal_id
            snap = _get_snapshot_store().get(req_id)
            if snap and "rec" in snap:
                snap["carbs"] = c_val
                snap["fat"] = f_val
                snap["protein"] = p_val
                
                # Recalculate Bolus
                user_settings, resolved_user_id = await get_bot_user_settings_with_user_id()
                base_payload = snap.get("payload")
                if base_payload:
                    req_v2 = base_payload.model_copy(deep=True)
                    req_v2.carbs_g = c_val
                    req_v2.fat_g = f_val
                    req_v2.protein_g = p_val
                else:
                    req_v2 = BolusRequestV2(
                        carbs_g=c_val,
                        fat_g=f_val,
                        protein_g=p_val,
                        meal_slot=(snap["rec"].used_params.meal_slot if snap.get("rec") else "lunch"),
                        target_mgdl=user_settings.targets.mid,
                    )

                req_v2.confirm_iob_unknown = True
                req_v2.confirm_iob_stale = True

                new_rec = await _calculate_bolus_with_context(
                    req_v2,
                    user_settings=user_settings,
                    resolved_user_id=resolved_user_id,
                    snapshot_user_id=snap.get("user_id"),
                )
                if snap.get("user_id") is None and resolved_user_id:
                    snap["user_id"] = resolved_user_id
                
                snap["rec"] = new_rec
                snap["payload"] = req_v2
                
                # Construct updated summary message
                total_u, rec_u, later_u, duration_min = _resolve_bolus_delivery(new_rec)
                lines = []
                lines.append(f"🍽️ **Comida Actualizada**")
                lines.append(f"Macros: C:{c_val} F:{f_val} P:{p_val}")
                lines.append("")
                lines.append(f"Resultado total: **{total_u:g} U**")
                if later_u > 0:
                    lines.append(f"Ahora: **{rec_u:g} U**")
                    lines.append(f"Planificada para revisar tras {duration_min} min: **{later_u:g} U**")
                
                if new_rec.explain:
                    lines.append("")
                    for ex in new_rec.explain:
                        lines.append(f"• {ex}")
                
                lines.append("")
                lines.append(f"¿Registrar {rec_u} U?")
                
                kb = [
                    [
                        InlineKeyboardButton(f"✅ Poner {rec_u} U", callback_data=f"accept|{req_id}"),
                        InlineKeyboardButton("✏️ Editar Bolo", callback_data=f"edit_dose|{rec_u}|{req_id}"),
                        InlineKeyboardButton("✏️ Nutrientes", callback_data=f"edit_macros|{req_id}")
                    ],
                    [
                        InlineKeyboardButton("❌ Ignorar", callback_data=f"cancel|{req_id}")
                    ]
                ]
                _maybe_append_exercise_button(kb, request_id=req_id, label="🏃 Añadir ejercicio")
                _log_bolus_keyboard_build(
                    update,
                    request_id=req_id,
                    bolus_mode="simple",
                    keyboard=kb,
                )
                
                await reply_text(update, context, "\n".join(lines), reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                health.record_action("macro_edit_success", True)
            else:
                 await reply_text(update, context, "❌ Sesión caducada.")
                 
        except ValueError:
            await reply_text(update, context, "⚠️ Formato incorrecto. Usa: `Carbos Grasas Proteinas` (ej: `50 20 15`) o solo `Carbos`.")
        return



    # 0. Intercept Basal Edit
    if context.user_data.get("editing_basal"):
        try:
            val = float(text.replace(",", "."))
            del context.user_data["editing_basal"]
            
            kb = [
                [InlineKeyboardButton(f"✅ Confirmar {val} U", callback_data=f"basal_confirm|{val}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="basal_cancel")]
            ]
            await reply_text(update, context, f"¿Registrar Basal: **{val} U**?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
            return
        except ValueError:
            await reply_text(update, context, "⚠️ Introduce un número válido.")
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
        p = await _hydrate_bolus_snapshot(p)
        _get_snapshot_store().set(p["id"], p)
        
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
             
             # Smart Mode Selection: If we have secondary (Last), we combine.
             s_id = getattr(bot_reply, "secondary_site_id", None)
             
             # Convention enforced by Router: 
             # site_id = NEXT (Green)
             # secondary_site_id = LAST (Red)
             
             img_bytes = generate_injection_image(
                 site_id=bot_reply.site_id, 
                 assets_dir=assets, 
                 mode="next_last_combined" if s_id else "selected",
                 next_site_id=bot_reply.site_id,
                 last_site_id=s_id
             )
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
    fat = float(args.get("fat", 0) or 0)
    protein = float(args.get("protein", 0) or 0)
    fiber = float(args.get("fiber", 0) or 0)
    insulin_req = args.get("insulin")
    insulin_req = float(insulin_req) if insulin_req is not None else None
    notes = args.get("notes", "Via Chat")
    
    chat_id = update.effective_chat.id
    
    await reply_text(update, context, "⚙️ Procesando solicitud de tratamiento...")
    
    # 1. Resolve User Settings
    user_settings, resolved_user_id = await get_bot_user_settings_with_user_id()

    # 2. Recommendation Logic (Shared Engine)
    # ---------------------------------------------------------
    # Generate Request ID
    request_id = str(uuid.uuid4())[:8] # Short 8-char ID for UX
    
    # Resolve Parameters
    slot = get_current_meal_slot(user_settings)
    
    # Create Request V2
    req_v2 = BolusRequestV2(
        carbs_g=carbs,
        # Target is resolved centrally from targets.<meal_slot>.
        meal_slot=slot,
        fat_g=fat, 
        protein_g=protein,
        fiber_g=fiber,
        confirm_iob_unknown=True,
        confirm_iob_stale=True,
    )

    # Manual Insulin Override?
    if insulin_req is not None:
         pass

    try:
        bolus_user_id = _resolve_bolus_user_id(user_settings, resolved_user_id)
        rec = await calculate_bolus_for_bot(
            req_v2,
            username=bolus_user_id,
        )
    except Exception as exc:
        await reply_text(update, context, f"❌ Error calculando bolo: {exc}")
        return

    bg_val = rec.glucose.mgdl if rec.glucose else None

    # Override if manual input was given (but keep breakdown for reference if possible, or just overwrite)
    if insulin_req is not None:
        rec.total_u_final = insulin_req
        rec.total_u = insulin_req
        rec.kind = "normal"
        rec.upfront_u = insulin_req
        rec.later_u = 0.0
        rec.duration_min = 0
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

    msg_text, fiber_dual_rec, notes = _build_bolus_message(
        rec,
        carbs=carbs,
        fat=fat,
        protein=protein,
        bg_val=bg_val,
        request_id=request_id,
        notes=notes,
    )

    # 4. Save Snapshot
    _get_snapshot_store().set(request_id, {
        "rec": rec,
        "carbs": carbs,
        "fat": fat,
        "protein": protein,
        "fiber": fiber,
        "bg": bg_val,
        "notes": notes,
        "user_id": resolved_user_id,
        "source": "CalculateBolus",
        "ts": datetime.now(),
        "payload": req_v2
    })
    logger.info(f"Snapshot saved for request_{request_id}. Keys: {len(_get_snapshot_store())}")
    
    # 5. Send Card
    # ---------------------------------------------------------
    from app.services.async_injection_manager import AsyncInjectionManager
    injection_mgr = AsyncInjectionManager("admin")
    next_site = await injection_mgr.get_next_site("bolus")
    
    # Enrich message with recommendation
    msg_text += f"\n\n📍 Sugerencia: {next_site['name']} {next_site['emoji']}"

    
    _, immediate_u, _, _ = _resolve_bolus_delivery(rec)
    keyboard = _build_bolus_recommendation_keyboard(
        update,
        request_id=request_id,
        rec_u=immediate_u,
        user_settings=user_settings,
        fiber_dual_rec=fiber_dual_rec,
    )
    
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


async def _apply_exercise_recalculation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    request_id: str,
    intensity: str,
    minutes: int,
    source: str,
    query: Optional[Any] = None,
) -> None:
    snapshot = _get_snapshot_store().get(request_id)
    if not snapshot:
        await reply_text(update, context, "⚠️ Sesión caducada. Recalcula el bolo.")
        return

    user_settings, resolved_user_id = await get_bot_user_settings_with_user_id()
    base_payload = snapshot.get("payload")
    if base_payload:
        req_v2 = base_payload.model_copy(deep=True)
    else:
        req_v2 = BolusRequestV2(
            carbs_g=snapshot.get("carbs", 0.0),
            fat_g=snapshot.get("fat", 0.0),
            protein_g=snapshot.get("protein", 0.0),
            fiber_g=snapshot.get("fiber", 0.0),
            meal_slot=get_current_meal_slot(user_settings),
        )

    req_v2.exercise.planned = True
    req_v2.exercise.minutes = minutes
    req_v2.exercise.intensity = intensity
    req_v2.confirm_iob_unknown = True
    req_v2.confirm_iob_stale = True

    try:
        snapshot_user_id = snapshot.get("user_id")
        new_rec = await _calculate_bolus_with_context(
            req_v2,
            user_settings=user_settings,
            resolved_user_id=resolved_user_id,
            snapshot_user_id=snapshot_user_id,
        )
    except Exception as exc:
        await reply_text(update, context, f"❌ Error recalculando bolo: {exc}")
        return

    snapshot["rec"] = new_rec
    snapshot["payload"] = req_v2
    snapshot["exercise"] = {
        "intensity": intensity,
        "minutes": minutes,
    }
    if snapshot.get("user_id") is None and resolved_user_id:
        snapshot["user_id"] = resolved_user_id

    exercise_summary = f"{_format_exercise_label(intensity)}, {minutes} min"
    msg_text, fiber_dual_rec, _ = _build_bolus_message(
        new_rec,
        carbs=snapshot.get("carbs", 0.0),
        fat=snapshot.get("fat", 0.0),
        protein=snapshot.get("protein", 0.0),
        bg_val=new_rec.glucose.mgdl if new_rec.glucose else None,
        request_id=request_id,
        notes=snapshot.get("notes", ""),
        exercise_summary=exercise_summary,
    )

    _, rec_u, _, _ = _resolve_bolus_delivery(new_rec)
    keyboard = _build_bolus_recommendation_keyboard(
        update,
        request_id=request_id,
        rec_u=rec_u,
        user_settings=user_settings,
        fiber_dual_rec=fiber_dual_rec,
    )

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await edit_message_text_safe(query, text=msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await reply_text(update, context, msg_text, reply_markup=reply_markup, parse_mode="Markdown")






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
        # A single persistent episode engine owns proactive glucose alerts.
        # This survives restarts/failover and avoids duplicate trend messages.
        await proactive.companion_check(trigger="auto")
        
        # [ML] Data Collection Step
        try:
             await _collect_ml_data()
        except Exception as ml_e:
             logger.warning(f"ML collection failed: {ml_e}")

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
    mode, reason, _ = await _acquire_leader_lock(mode, reason)
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

    # ALWAYS create the bot app instance so we can SEND messages from any worker
    # even if we are not the Polling Leader.
    _bot_app = create_bot_app()
    if not _bot_app:
        health.set_mode(BotMode.ERROR, reason)
        health.set_error("No TELEGRAM_BOT_TOKEN")
        return

    # Initialize coroutines (needed for send_message)
    try:
        await _bot_app.initialize()
    except Exception as e:
        logger.error(f"Bot app initialization failed: {e}")
        _bot_app = None
        return

    if mode == BotMode.DISABLED:
        # Special Case: Emergency logic or Follower Logic
        if reason in {"emergency_mode_send_only", "leader_lock_standby"}:
             logger.info("⚠️ Bot in SEND-ONLY mode (%s). Not starting Polling/Webhook.", reason)
        elif reason == "locked_by_other":
             logger.info("🔒 Bot Worker is FOLLOWER (Lock held by other). Initialized in SEND-ONLY mode.")
        else:
             logger.info("Bot DISABLED (Reason: %s). Initialized in SEND-ONLY mode (for emergencies).", reason)
        
        # We do NOT return here blindly anymore, but we DO NOT call start() or webhook setup.
        # This ensures _bot_app is available for proactive sends (e.g. from integrations).
        return

    # Track updates for both webhook and polling modes
    _bot_app.add_handler(MessageHandler(filters.ALL, _mark_update_handler), group=100)

    public_url, public_url_source = config.get_public_bot_url_with_source()
    webhook_secret = config.get_telegram_webhook_secret()

    # Start the app (Updater/Scheduler) only if we are the LEADER (Enabled/Webhook/Polling)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            await _bot_app.start()
            logger.info("✅ Bot STARTED successfully (Leader).")
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

    async def _webhook_guardian_task() -> None:
        """
        Periodically ensures no webhook is set (Guardian for Polling Mode).
        This protects against 'Split Brain' scenarios where an external service (Render)
        re-registers the webhook, causing the NAS bot to crash with Conflict errors.
        """
        logger.info("🛡️ Webhook Guardian started.")
        while True:
            try:
                # Check 
                try:
                    info = await _bot_app.bot.get_webhook_info()
                    if info.url:
                        logger.warning(f"🛡️ Guardian detected ROGUE webhook: {info.url}")
                        logger.warning("🛡️ Guardian enforcing cleanup...")
                        await _bot_app.bot.delete_webhook(drop_pending_updates=False)
                        logger.info("🛡️ Webhook deleted. Polling should resume.")
                    else:
                        # All good
                        pass
                except Conflict:
                    # If we are already in conflict, blindly delete
                    await _bot_app.bot.delete_webhook()
                except Exception as inner:
                     logger.debug(f"Guardian check warning: {inner}")

                # Check infrequently to avoid rate limits, but fast enough to heal
                await asyncio.sleep(15) 
            except asyncio.CancelledError:
                logger.info("🛡️ Guardian stopped.")
                break
            except Exception as e:
                logger.error(f"Guardian Loop Error: {e}")
                await asyncio.sleep(10)

    async def _start_polling_with_retry() -> None:
        nonlocal backoff_schedule
        
        # 1. Start the Guardian immediately to clear the path
        asyncio.create_task(_webhook_guardian_task(), name="webhook_guardian")

        # 2. Initial heavy cleanup
        logger.warning(f"Initializing POLLING. Enforcing webhook cleanup...")
        try:
            await _bot_app.bot.delete_webhook(drop_pending_updates=False)
        except Exception: 
            pass
        await asyncio.sleep(1)

        # 3. Start Polling
        for attempt, delay in enumerate(backoff_schedule, start=1):
            try:
                await _bot_app.updater.start_polling(
                    poll_interval=poll_interval,
                    timeout=read_timeout,
                    bootstrap_retries=2,
                )
                health.set_mode(BotMode.POLLING, fallback_reason)
                logger.warning("Polling started (interval=%s, timeout=%s)", poll_interval, read_timeout)
                return
            except Exception as exc:
                msg = f"Polling start attempt {attempt} failed: {exc}"
                logger.warning(msg)
                health.set_error(str(exc))
                await asyncio.sleep(delay)
        
        # Final attempt
        try:
             await _bot_app.updater.start_polling(poll_interval=poll_interval, timeout=read_timeout)
        except Exception as e:
             logger.error(f"Polling failed final: {e}")

    logger.info("Polling enabled (background).")
    _polling_task = asyncio.create_task(_start_polling_with_retry(), name="telegram-bot-polling")

async def shutdown() -> None:
    """Called on FastAPI shutdown."""
    global _bot_app
    global _polling_task
    global _leader_task
    global _leader_instance_id
    
    if _polling_task:
        logger.info("Canceling Telegram polling task...")
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            logger.info("Polling task cancelled.")
        except Exception as e:
            logger.error(f"Error cancelling polling task: {e}")

    if _leader_task:
        logger.info("Canceling bot leader heartbeat...")
        current_task = asyncio.current_task()
        if _leader_task is not current_task:
            _leader_task.cancel()
            try:
                await _leader_task
            except asyncio.CancelledError:
                logger.info("Leader heartbeat cancelled.")
            except Exception as e:
                logger.error("Error cancelling leader heartbeat: %s", e)
        _leader_task = None

    if _leader_instance_id:
        session_factory = get_session_factory()
        if session_factory:
            try:
                async with session_factory() as session:
                    released = await release_bot_leader(session, _leader_instance_id)
                    logger.info("bot_leader_lock_release owner=%s released=%s", _leader_instance_id, released)
                if released:
                    _leader_instance_id = None
            except Exception as exc:
                logger.warning("bot_leader_lock_release failed owner=%s error=%s", _leader_instance_id, exc)

    # Cancel Guardian Task if running
    for task in asyncio.all_tasks():
        if task.get_name() == "webhook_guardian":
            logger.info("Cancelling Webhook Guardian...")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    if not _bot_app:
        return

    logger.info("Shutting down Telegram Bot...")
    updater = getattr(_bot_app, "updater", None)
    if updater is None:
        logger.debug("Telegram updater not configured; skipping stop.")
    elif getattr(updater, "running", False):
        logger.info("Stopping Telegram updater...")
        try:
            await updater.stop()
        except RuntimeError as exc:
            logger.warning("Telegram updater stop skipped: %s", exc)
    else:
        logger.debug("Telegram updater not running; skipping stop.")

    if getattr(_bot_app, "running", False):
        try:
            await _bot_app.stop()
        except RuntimeError as exc:
            logger.warning("Telegram Bot stop skipped: %s", exc)
    else:
        logger.info("Telegram Bot application not running; skipping stop.")

    try:
        await _bot_app.shutdown()
    except RuntimeError as exc:
        logger.warning("Telegram Bot shutdown skipped: %s", exc)
    finally:
        _bot_app = None

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
MEAL_NOTIFY_CACHE: Dict[str, float] = {}
MEAL_NOTIFY_CACHE_TTL_SECONDS = 24 * 60 * 60


def _classify_nutrition_delivery_error(error):
    from app.services.nutrition_notification_outbox import DeliveryResult

    if isinstance(error, RetryAfter):
        retry_after = getattr(error, "retry_after", None)
        if hasattr(retry_after, "total_seconds"):
            retry_after = int(retry_after.total_seconds())
        return DeliveryResult(
            status="retry_scheduled",
            error=f"RetryAfter: {error}",
            retry_after_seconds=int(retry_after) if retry_after is not None else None,
        )
    if isinstance(error, TimedOut):
        return DeliveryResult(status="delivery_unknown", error=f"TimedOut: {error}")
    if isinstance(error, (BadRequest, Forbidden, InvalidToken)):
        return DeliveryResult(status="failed", error=f"{type(error).__name__}: {error}")
    if isinstance(error, NetworkError):
        return DeliveryResult(status="delivery_unknown", error=f"NetworkError: {error}")
    return DeliveryResult(status="delivery_unknown", error=f"{type(error).__name__}: {error}")


async def on_new_meal_received(
    carbs: float,
    fat: float,
    protein: float,
    fiber: float,
    source: str,
    origin_id: Optional[str] = None,
    *,
    outbox_delivery: bool = False,
    meal_id: Optional[str] = None,
    meal_revision: Optional[str] = None,
    meal_user_id: Optional[str] = None,
    imported_meal_id: Optional[str] = None,
    imported_meal_fingerprint: Optional[str] = None,
    imported_meal_version: Optional[int] = None,
    meal_slot: Optional[str] = None,
    edit_message_id: Optional[int] = None,
    skip_duplicate_checks: bool = False,
):
    """
    Called by integrations.py when a new meal is ingested.
    Triggers a proactive notification.
    """
    global _bot_app
    from app.services.nutrition_notification_outbox import DeliveryResult

    if origin_id and not outbox_delivery and not skip_duplicate_checks:
        now_ts = time.time()
        expired = [
            key for key, ts in MEAL_NOTIFY_CACHE.items()
            if now_ts - ts > MEAL_NOTIFY_CACHE_TTL_SECONDS
        ]
        for key in expired:
            MEAL_NOTIFY_CACHE.pop(key, None)

        if origin_id in MEAL_NOTIFY_CACHE:
            logger.info("meal_event_duplicate_skipped event_id=%s source=%s", origin_id, source)
            return DeliveryResult(status="sent")
        MEAL_NOTIFY_CACHE[origin_id] = now_ts

    if not _bot_app:
        logger.info("meal_event_received_no_bot event_id=%s source=%s", origin_id, source)
        return DeliveryResult(status="retry_scheduled", error="bot_unavailable")

    chat_id = config.get_allowed_telegram_user_id()
    if not chat_id:
        logger.info("meal_event_received_no_chat_id event_id=%s source=%s", origin_id, source)
        return DeliveryResult(status="failed", error="chat_id_unavailable")

    logger.info(
        "meal_event_received event_id=%s source=%s chat_id=%s",
        origin_id,
        source,
        chat_id,
    )
    logger.info(f"Bot proactively notifying meal: {carbs}g F:{fat} P:{protein} Fib:{fiber} from {source} (id={origin_id})")
    now_utc = datetime.now(timezone.utc)
    settings = get_settings()

    # Warsaw Observability
    try:
        if hasattr(settings, "warsaw") and settings.warsaw.enabled:
             if (fat or 0) + (protein or 0) < 1.0:
                 logger.info("mfp_missing_kcal_warsaw_skipped: Low/Missing Fat/Protein data from MFP")
    except Exception as e:
        logger.error(f"Error checking Warsaw conditions: {e}")
    
    # 1. Gather Context
    store = DataStore(Path(settings.data.data_dir))
    user_settings, resolved_user_id = await resolve_bot_user_settings()
    companion_user_id = resolved_user_id or config.get_bot_default_username()

    # Resolve mutable source totals against durable confirmed coverage.  The
    # calculation below receives only the still-uncovered nutrition; IOB stays
    # available exclusively to the correction component in the core engine.
    coverage_context = None
    calculation_carbs = carbs
    calculation_fat = fat
    calculation_protein = protein
    calculation_fiber = fiber
    if meal_id:
        from app.services.meal_coverage_service import get_meal_state, state_context

        coverage_user_id = meal_user_id or resolved_user_id or companion_user_id or "admin"
        async with SessionLocal() as session:
            coverage_state = await get_meal_state(
                session,
                user_id=coverage_user_id,
                external_meal_id=meal_id,
            )
        if coverage_state:
            coverage_context = state_context(coverage_state)
            meal_revision = coverage_context["revision"]
            current = coverage_context["current"]
            delta = coverage_context["delta"]
            carbs = float(current["carbs"])
            fat = float(current["fat"])
            protein = float(current["protein"])
            fiber = float(current["fiber"])
            calculation_carbs = float(delta["carbs"])
            calculation_fat = float(delta["fat"])
            calculation_protein = float(delta["protein"])
            calculation_fiber = float(delta["fiber"])
            logger.info(
                "meal_incremental_calculation meal_key=%s revision=%s total=%s covered=%s delta=%s reductions=%s",
                coverage_context["meal_key"],
                coverage_context["revision"],
                coverage_context["current"],
                coverage_context["covered"],
                coverage_context["delta"],
                coverage_context["reductions"],
            )

    episode_origin_id = _meal_episode_origin_id(origin_id, meal_revision)
    if episode_origin_id and not skip_duplicate_checks:
        from app.services.companion_service import get_episode_by_fingerprint
        async with SessionLocal() as session:
            existing_episode = await get_episode_by_fingerprint(
                companion_user_id, f"meal_detected:{episode_origin_id}", session
            )
        if existing_episode and existing_episode.status not in ("resolved", "expired"):
            logger.info(
                "meal_event_persistent_duplicate_skipped event_id=%s revision=%s",
                origin_id,
                meal_revision,
            )
            return
    
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
        # `unknown` is retained for compatibility with pre-v2 context producers,
        # which already performed their own freshness check. The current
        # resolver always sends an explicit status and boolean.
        legacy_context_usable = ctx_res.glucose_status == "unknown"
        if ctx_res.bg_mgdl is not None and (
            ctx_res.usable_for_dosing or legacy_context_usable
        ):
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

    if not fetched and isinstance(ctx_res, tools.ToolError):
        if prefer_nightscout:
            fetched = await _fetch_from_nightscout()
            if not fetched and dexcom_ready:
                fetched = await _fetch_from_dexcom()
        elif dexcom_ready:
            fetched = await _fetch_from_dexcom()
            if not fetched and prefer_nightscout:
                fetched = await _fetch_from_nightscout()
    
    if not fetched and isinstance(ctx_res, tools.ToolError):
        await _fetch_from_local_db()

    if bg_datetime:
        bg_age = max(0.0, (now_utc - bg_datetime).total_seconds() / 60.0)

    
    # 2. Calculate Bolus V2 (Snapshot Safe)
    # -----------------------------------------------------
    request_id = str(uuid.uuid4())[:8]

    from app.services.imported_meal_service import normalize_meal_type

    imported_slot = normalize_meal_type(meal_slot)
    if imported_slot in {"breakfast", "lunch", "dinner", "snack"}:
        slot = imported_slot
    else:
        if meal_slot:
            logger.warning(
                "meal_event_invalid_slot_fallback event_id=%s meal_slot=%s",
                origin_id,
                meal_slot,
            )
        slot = get_current_meal_slot(user_settings)
    
    # calculate staleness
    is_stale_reading = False
    if bg_datetime and bg_age > 20:
         is_stale_reading = True
         logger.warning(f"Glucose reading is stale! Age: {bg_age:.1f} mins")
    
    req_v2 = BolusRequestV2(
        carbs_g=calculation_carbs,
        fat_g=calculation_fat,
        protein_g=calculation_protein,
        fiber_g=calculation_fiber,
        meal_slot=slot,
        bg_mgdl=bg_val,
        confirm_iob_unknown=True,
        confirm_iob_stale=True,
    )

    telegram_username = getattr(user_settings, "telegram_username", None)
    if telegram_username:
        bolus_username = telegram_username
    else:
        bolus_username = resolved_user_id or getattr(user_settings, "user_id", None) or "admin"
        logger.info(
            "proactive_meal_username_fallback: using user_id='%s' (telegram_username missing)",
            bolus_username,
        )

    rec = await calculate_bolus_for_bot(
        req_v2,
        username=bolus_username,
    )

    # Store Snapshot
    _get_snapshot_store().set(request_id, {
        "rec": rec,
        # Treatments record only newly covered nutrition.  The full mutable
        # source totals remain in coverage_context for audit and display.
        "carbs": calculation_carbs,
        "fat": calculation_fat,
        "protein": calculation_protein,
        "fiber": calculation_fiber,
        "meal_total": {"carbs": carbs, "fat": fat, "protein": protein, "fiber": fiber},
        "source": source,
        "origin_id": origin_id,
        "episode_origin_id": episode_origin_id,
        "user_id": meal_user_id or resolved_user_id,
        "meal_id": meal_id,
        "meal_revision": meal_revision,
        "meal_coverage": coverage_context,
        "imported_meal_id": imported_meal_id,
        "imported_meal_fingerprint": imported_meal_fingerprint,
        "imported_meal_version": imported_meal_version,
        "calculation_id": request_id,
        "ts": datetime.now(),
        "payload": req_v2,
    })

    # 3. Message (Strict Format matching Core Engine)
    # -----------------------------------------------------
    total_u, rec_u, later_u, duration_min = _resolve_bolus_delivery(rec)

    downward_trends = {"DoubleDown", "SingleDown", "FortyFiveDown", "down", "falling"}
    configured_wait = max(0, int(user_settings.insulin.pre_bolus_min or 0))
    if bg_val is None or is_stale_reading:
        wait_message = "Espera previa: sin estimar porque la glucosa no es fiable."
    elif bg_val < 90 or bg_trend in downward_trends:
        wait_message = "Espera previa: no recomendada con glucosa baja o descendente; revisa tu pauta."
    elif rec_u <= 0:
        wait_message = "Espera previa: no aplica porque no hay bolo de comida."
    else:
        wait_message = f"Espera orientativa tras confirmar el bolo: {configured_wait} min (tu perfil)."
    
    lines = []
    # Sanitize source for MarkdownV2
    def escape_md(text: str) -> str:
        if not text: return ""
        # Characters to escape in MarkdownV2 (except maybe bold/italic markers if we want them)
        # But here we treat source/explanation as raw text usually.
        # Telegram Markdown (V1) vs MarkdownV2. The bot uses "Markdown" (V1) in send (parse_mode="Markdown").
        # V1 only needs [ ] ( ) * _ ` be careful.
        # Let's escape assuming parse_mode="Markdown" (V1 legacy).
        return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

    safe_source = escape_md(source) if source else "Unknown"
    is_incremental_update = bool(
        coverage_context
        and any(float(value or 0) > 0 for value in coverage_context["covered"].values())
    )
    title = "Comida actualizada" if is_incremental_update else "Nueva Comida Detectada"
    lines.append(f"🍽️ **{title}** ({safe_source})")
    lines.append("")
    if coverage_context:
        covered = coverage_context["covered"]
        delta = coverage_context["delta"]
        reductions = coverage_context["reductions"]
        lines.append(f"Total comida: **{carbs:g} g HC**")
        lines.append(f"Ya cubiertos: **{covered['carbs']:g} g HC**")
        lines.append(f"Nuevos: **+{delta['carbs']:g} g HC**")
        if coverage_context.get("last_confirmed_bolus") is not None:
            confirmed_ago = ""
            try:
                confirmed_at = datetime.fromisoformat(coverage_context["confirmed_at"])
                if confirmed_at.tzinfo is None:
                    confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
                minutes_ago = max(
                    0,
                    int((datetime.now(timezone.utc) - confirmed_at).total_seconds() / 60),
                )
                confirmed_ago = f" hace {minutes_ago} min"
            except (TypeError, ValueError):
                pass
            lines.append("")
            lines.append(
                f"Bolo previo confirmado: **{coverage_context['last_confirmed_bolus']:g} U**{confirmed_ago}"
            )
        lines.append(f"IOB actual: **{iob_u:.2f} U**")
        if any(float(value or 0) > 0 for value in reductions.values()):
            lines.append(
                "⚠️ La comida se ha reducido respecto a lo ya cubierto; "
                "no se genera insulina negativa."
            )
        lines.append("")
        if float(delta["carbs"]) <= 0:
            lines.append("No se han detectado hidratos nuevos que necesiten cobertura.")
        lines.append("**Cálculo adicional:**")
        lines.append(f"Resultado adicional: **{total_u:g} U**")
    else:
        lines.append(f"Resultado total: **{total_u:g} U**")
    if later_u > 0:
        lines.append(f"Dosis inmediata: **{rec_u:g} U**")
        lines.append(f"Planificada para revisar tras {duration_min} min: **{later_u:g} U**")
    lines.append("")
    lines.append(wait_message)
    lines.append("")
    
    # Use the explanation from the core engine to match App exactly
    if rec.explain:
        for ex in rec.explain:
            safe_ex = escape_md(ex)
            lines.append(f"• {safe_ex}")
            
    lines.append("")
    result_label = "Total adicional calculado" if coverage_context else "Total calculado"
    lines.append(f"{result_label}: {rec.total_u_raw:.2f} (Base) → {rec.total_u_final} U (Final)")
    lines.append("")
    lines.append(f"¿Registrar {rec_u} U?")
    
    msg_text = "\n".join(lines)
    
    keyboard = [
        [
            InlineKeyboardButton(f"✅ Poner {rec_u} U", callback_data=f"accept|{request_id}"),
            InlineKeyboardButton("✏️ Editar Bolo", callback_data=f"edit_dose|{rec_u}|{request_id}"),
            InlineKeyboardButton("❌ Ignorar", callback_data=f"cancel|{request_id}")
        ],
        [
            InlineKeyboardButton(f"✏️ Editar Macros", callback_data=f"edit_macros|{request_id}")
        ],
    ]
    _maybe_append_exercise_button(keyboard, request_id=request_id, label="🏃 Añadir ejercicio")
    keyboard.append([
        InlineKeyboardButton("🌅 Desayuno", callback_data=f"set_slot|breakfast|{request_id}"),
        InlineKeyboardButton("🍕 Comida", callback_data=f"set_slot|lunch|{request_id}"),
        InlineKeyboardButton("🍽️ Cena", callback_data=f"set_slot|dinner|{request_id}"),
        InlineKeyboardButton("🥨 Snack", callback_data=f"set_slot|snack|{request_id}"),
    ])
    _log_bolus_keyboard_build(
        None,
        request_id=request_id,
        bolus_mode="simple",
        keyboard=keyboard,
    )
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        telegram_started = time.perf_counter()
        if edit_message_id is not None:
            sent_message = await _bot_app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=edit_message_id,
                text=msg_text,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
        else:
            sent_message = await bot_send(
                chat_id=chat_id,
                text=msg_text,
                bot=_bot_app.bot,
                reply_markup=reply_markup,
                parse_mode="Markdown",
                log_context="proactive_meal",
                raise_on_error=outbox_delivery,
            )
        logger.info(
            "[TELEGRAM] event_id=%s api_duration_ms=%s message_id=%s",
            origin_id,
            int((time.perf_counter() - telegram_started) * 1000),
            getattr(sent_message, "message_id", edit_message_id),
        )
        if sent_message is None:
            return DeliveryResult(status="retry_scheduled", error="telegram_send_failed")
        if episode_origin_id:
            from app.services.companion_service import (
                record_meal_episode,
                resolve_superseded_meal_episodes,
            )
            async with SessionLocal() as session:
                # Telegram has accepted the replacement message. Only now is
                # it safe to hide every older revision of this same meal.
                if origin_id and meal_revision:
                    await resolve_superseded_meal_episodes(
                        companion_user_id,
                        origin_id,
                        episode_origin_id,
                        session,
                    )
                await record_meal_episode(
                    companion_user_id,
                    episode_origin_id,
                    wait_message,
                    {
                        "carbs_g": carbs,
                        "fat_g": fat,
                        "protein_g": protein,
                        "fiber_g": fiber,
                        "bg": bg_val,
                        "trend": bg_trend,
                        "wait_minutes": configured_wait if "orientativa" in wait_message else None,
                    },
                    session,
                )
        return DeliveryResult(
            status="sent",
            telegram_message_id=str(getattr(sent_message, "message_id", "")) or None,
        )
    except Exception as e:
        logger.error(f"Failed to send proactive message: {e}")
        return _classify_nutrition_delivery_error(e)


def _imported_meal_review_card(meal) -> tuple[str, InlineKeyboardMarkup]:
    from app.utils.timezone import get_user_timezone

    labels = {
        "breakfast": "DESAYUNO", "lunch": "COMIDA", "dinner": "CENA",
        "snack": "SNACK", "snacks": "SNACK", "comida": "COMIDA",
        "almuerzo": "COMIDA", "cena": "CENA", "desayuno": "DESAYUNO",
    }
    title = labels.get(meal.meal_type.lower(), meal.meal_type.upper())
    local_seen = meal.last_seen_at
    if local_seen and local_seen.tzinfo is None:
        local_seen = local_seen.replace(tzinfo=timezone.utc)
    user_timezone = get_user_timezone(str(getattr(meal, "user_id", None) or "admin"))
    stamp = local_seen.astimezone(user_timezone).strftime("%H:%M") if local_seen else ""
    lines = [f"🍽 {title} · {stamp}", ""]
    for index, food in enumerate(meal.foods, start=1):
        amount = " ".join(part for part in (str(food.get("quantity") or ""), str(food.get("unit") or "")) if part).strip()
        lines.append(f"{index}. {food.get('name') or 'Alimento'}")
        lines.append(f"   {(amount + ' · ') if amount else ''}{float(food.get('carbs_g') or 0):g} g HC")
        lines.append("")
    lines.extend(["───────────────", f"TOTAL: {meal.calculated_carbs:g} g HC", "", "Fuente: MyFitnessPal"])

    if meal.status == "DISCARDED":
        lines.extend(["", "🗑 Esta versión fue descartada."])
        return "\n".join(lines), InlineKeyboardMarkup([])

    if meal.validation_error == "carb_total_mismatch":
        difference = abs(float(meal.source_carbs) - float(meal.calculated_carbs))
        lines.extend([
            "", "⚠️ Datos inconsistentes", "",
            f"MyFitnessPal indica: {meal.source_carbs:g} g HC",
            f"Suma de alimentos: {meal.calculated_carbs:g} g HC",
            f"Diferencia: {difference:g} g HC", "",
            "No se calculará ningún bolo hasta revisar la comida.",
        ])
    elif meal.validation_error:
        lines.extend(["", "⚠️ No se ha podido validar la comida.", "No se calculará ningún bolo."])
    elif meal.status == "UPDATED_TREATED":
        previous = float(meal.previous_calculated_carbs if meal.previous_calculated_carbs is not None else meal.calculated_carbs)
        change = float(meal.calculated_carbs) - previous
        bolus_at = meal.last_bolus_at
        if bolus_at and bolus_at.tzinfo is None:
            bolus_at = bolus_at.replace(tzinfo=timezone.utc)
        minutes_ago = int(max(0, (datetime.now(timezone.utc) - bolus_at).total_seconds() / 60)) if bolus_at else None
        lines.extend([
            "", "⚠️ COMIDA MODIFICADA",
            f"Anterior: {previous:g} g HC",
            f"Ahora: {meal.calculated_carbs:g} g HC",
            f"Cambio: {change:+g} g HC",
            "",
            f"Bolo previo: {meal.last_bolus_units:g} U" if meal.last_bolus_units is not None else "Bolo previo: registrado",
            f"Hace: {minutes_ago} min" if minutes_ago is not None else "Hace: tiempo no disponible",
            "",
            "Ya existe un bolo asociado. Al confirmar solo se evaluará la diferencia pendiente con IOB y glucosa actuales.",
        ])

    if meal.pending_source_version:
        pending = meal.pending_source_version
        compact_meal_id = str(meal.id).replace("-", "")
        pending_token = str(pending.get("fingerprint") or "")[:16]
        conflict_suffix = f"{compact_meal_id}|{pending_token}|{meal.version}"
        lines.extend([
            "", "⚠️ MyFitnessPal cambió después de tu revisión manual.",
            f"Nueva lectura MFP: {float(pending.get('calculated_carbs') or 0):g} g HC",
            f"Tu versión revisada: {meal.calculated_carbs:g} g HC",
        ])
        buttons = [
            [InlineKeyboardButton("Usar MFP", callback_data=f"im_u|{conflict_suffix}"), InlineKeyboardButton("Mantener revisada", callback_data=f"im_k|{conflict_suffix}")],
            [InlineKeyboardButton("Ver cambios", callback_data=f"im_diff|{meal.id}")],
        ]
        return "\n".join(lines), InlineKeyboardMarkup(buttons)

    if meal.validation_error:
        buttons = [
            [InlineKeyboardButton("🔄 Reintentar MFP", callback_data=f"im_refresh|{meal.id}")],
            [InlineKeyboardButton("✏️ Corregir manualmente", callback_data=f"im_edit|{meal.id}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data=f"im_discard|{meal.id}")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton("✅ Confirmar", callback_data=f"im_confirm|{meal.id}"), InlineKeyboardButton("✏️ Editar", callback_data=f"im_edit|{meal.id}")],
            [InlineKeyboardButton("🔄 Actualizar MFP", callback_data=f"im_refresh|{meal.id}"), InlineKeyboardButton("🗑 Descartar", callback_data=f"im_discard|{meal.id}")],
        ]
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def _deliver_imported_meal_review(payload: dict):
    from app.models.imported_meal import ImportedMeal
    from app.services.nutrition_notification_outbox import DeliveryResult

    meal_id = str(payload.get("imported_meal_id") or "")
    async with SessionLocal() as session:
        meal = await session.get(ImportedMeal, meal_id)
        if meal is None:
            return DeliveryResult(status="failed", error="imported_meal_missing")
        text_value, markup = _imported_meal_review_card(meal)
        chat_id = config.get_allowed_telegram_user_id()
        if not chat_id or not _bot_app:
            return DeliveryResult(status="retry_scheduled", error="telegram_unavailable")
        started = time.perf_counter()
        try:
            if meal.telegram_message_id:
                sent = await _bot_app.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=int(meal.telegram_message_id),
                    text=text_value,
                    reply_markup=markup,
                )
                message_id = str(getattr(sent, "message_id", meal.telegram_message_id))
            else:
                sent = await bot_send(
                    chat_id=chat_id,
                    text=text_value,
                    bot=_bot_app.bot,
                    reply_markup=markup,
                    log_context="imported_meal_review",
                    raise_on_error=True,
                )
                message_id = str(getattr(sent, "message_id", ""))
            meal.telegram_message_id = message_id or meal.telegram_message_id
            session.add(meal)
            await session.commit()
            logger.info(
                "[TELEGRAM] review event_id=%s queue_delay_ms=%s api_duration_ms=%s message_id=%s",
                meal.id,
                int(max(0, (datetime.now(timezone.utc) - (meal.last_seen_at.replace(tzinfo=timezone.utc) if meal.last_seen_at.tzinfo is None else meal.last_seen_at)).total_seconds() * 1000)),
                int((time.perf_counter() - started) * 1000),
                message_id,
            )
            return DeliveryResult(status="sent", telegram_message_id=message_id or None)
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return DeliveryResult(status="sent", telegram_message_id=meal.telegram_message_id)
            return _classify_nutrition_delivery_error(exc)
        except Exception as exc:
            return _classify_nutrition_delivery_error(exc)


async def deliver_nutrition_notification(payload: dict):
    from app.services.nutrition_notification_outbox import DeliveryResult

    try:
        if payload.get("review_required"):
            return await _deliver_imported_meal_review(payload)
        return await on_new_meal_received(
            float(payload.get("carbs") or 0),
            float(payload.get("fat") or 0),
            float(payload.get("protein") or 0),
            float(payload.get("fiber") or 0),
            str(payload.get("source") or "Importado"),
            origin_id=payload.get("origin_id"),
            outbox_delivery=True,
            meal_id=payload.get("meal_id"),
            meal_revision=payload.get("meal_revision"),
            meal_user_id=payload.get("user_id"),
            imported_meal_id=payload.get("imported_meal_id"),
            imported_meal_fingerprint=payload.get("imported_meal_fingerprint"),
            imported_meal_version=payload.get("imported_meal_version"),
            meal_slot=payload.get("meal_slot") or payload.get("meal_type"),
        )
    except Exception as exc:
        # Delivery errors are classified inside on_new_meal_received. An error
        # escaping here happened before Telegram was called, so retrying cannot
        # create a duplicate notification.
        logger.exception("Nutrition notification preparation failed")
        return DeliveryResult(status="retry_scheduled", error=f"pre_delivery:{exc}")


async def _sync_imported_meal_draft(session, meal) -> None:
    """Keep the review draft and incremental-coverage revision aligned."""
    from app.models.treatment import Treatment
    from app.services.meal_coverage_service import nutrition_revision, upsert_current_meal

    nutrition = {"carbs": meal.calculated_carbs, "fat": meal.fat, "protein": meal.protein, "fiber": meal.fiber}
    revision = nutrition_revision(nutrition, meal.fingerprint)
    await upsert_current_meal(
        session,
        user_id=meal.user_id,
        external_meal_id=meal.source_reference,
        source=meal.source,
        revision=revision,
        nutrition=nutrition,
    )
    draft = await session.get(Treatment, meal.draft_treatment_id) if meal.draft_treatment_id else None
    if meal.validation_error is None:
        if draft is None or float(draft.insulin or 0) > 0:
            draft = Treatment(
                id=str(uuid.uuid4()), user_id=meal.user_id, event_type="Meal Bolus",
                created_at=datetime.now(timezone.utc).replace(tzinfo=None), insulin=0.0,
                carbs=meal.calculated_carbs, fat=meal.fat, protein=meal.protein, fiber=meal.fiber,
                notes=f"Imported meal review: {meal.source_reference} #imported",
                entered_by="webhook-integration", is_uploaded=False,
            )
            session.add(draft)
            meal.draft_treatment_id = draft.id
        draft.carbs = meal.calculated_carbs
        draft.fat = meal.fat
        draft.protein = meal.protein
        draft.fiber = meal.fiber
        draft.calculation_trace = {
            "meal_import": {
                "schema_version": 2, "meal_id": meal.source_reference,
                "imported_meal_id": meal.id, "revision": revision,
                "revision_number": meal.version, "nutrition_total": nutrition,
                "foods": meal.foods,
            }
        }
        session.add(draft)
    session.add(meal)
    await session.flush()


async def _edit_imported_meal_card(bot, chat_id: int, meal) -> None:
    if not meal.telegram_message_id:
        return
    text_value, markup = _imported_meal_review_card(meal)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=int(meal.telegram_message_id),
            text=text_value, reply_markup=markup,
        )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


def _hermes_mfp_refresh_configuration() -> tuple[str | None, str | None, str | None]:
    """Resolve the server-side Hermes trigger without exposing its secret."""
    base_url = (os.getenv("HERMES_MFP_SYNC_TRIGGER_URL") or "").strip().rstrip("/")
    key = (
        os.getenv("HERMES_MFP_TRIGGER_KEY")
        or os.getenv("NUTRITION_INGEST_KEY")
        or os.getenv("NUTRITION_INGEST_SECRET")
    )
    missing = []
    if not base_url:
        missing.append("HERMES_MFP_SYNC_TRIGGER_URL")
    if not key:
        missing.append("HERMES_MFP_TRIGGER_KEY/NUTRITION_INGEST_KEY")
    if missing:
        return None, None, f"falta {' y '.join(missing)} en Bolus AI"
    endpoint = base_url if base_url.endswith("/mfp/sync-now") else f"{base_url}/mfp/sync-now"
    return endpoint, key, None


async def _trigger_hermes_refresh() -> tuple[str, str]:
    import httpx

    endpoint, key, configuration_error = _hermes_mfp_refresh_configuration()
    if configuration_error:
        return "failed", configuration_error
    try:
        async with httpx.AsyncClient(timeout=150.0) as client:
            response = await client.post(endpoint, headers={"X-Ingest-Key": key})
        status = ""
        ingest_status = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                status = str(body.get("status") or "").strip().lower()
                ingest_status = str(body.get("ingest_status") or "").strip().lower()
        except (TypeError, ValueError):
            pass
        reported_status = ingest_status or status
        detail = f"HTTP {response.status_code}" + (f" ({reported_status})" if reported_status else "")
        if (
            response.status_code in {202, 409}
            or status == "retry_scheduled"
            or ingest_status == "retry_scheduled"
        ):
            return "pending", detail
        if not response.is_success or status == "failed" or ingest_status == "failed":
            return "failed", detail
        return "success", detail
    except Exception as exc:
        return "failed", type(exc).__name__


async def _refresh_imported_meal_from_hermes(
    *, bot, chat_id: int, message_id: int, meal_id: str,
) -> None:
    """Refresh one review without re-enabling confirmation for queued data."""
    from app.models.imported_meal import ImportedMeal

    try:
        outcome, detail = await _trigger_hermes_refresh()
        if outcome == "pending":
            pending_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Comprobar de nuevo", callback_data=f"im_refresh|{meal_id}")],
                [InlineKeyboardButton("🗑 Descartar", callback_data=f"im_discard|{meal_id}")],
            ])
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=(
                    f"⏳ Actualización de MyFitnessPal pendiente: {detail}\n\n"
                    "Hermes todavía no ha entregado la nueva lectura. La confirmación "
                    "permanece bloqueada para evitar calcular con nutrientes anteriores."
                ),
                reply_markup=pending_markup,
            )
            return

        async with SessionLocal() as session:
            refreshed_meal = await session.get(ImportedMeal, meal_id)
            if refreshed_meal is not None:
                review_text, review_markup = _imported_meal_review_card(refreshed_meal)
            else:
                review_text, review_markup = "La comida ya no está disponible.", None
        result_text = (
            f"✅ MyFitnessPal actualizado: {detail}"
            if outcome == "success" else f"⚠️ No se pudo actualizar MFP: {detail}"
        )
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"{result_text}\n\n{review_text}",
            reply_markup=review_markup,
        )
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        logger.exception("Hermes MFP refresh Telegram edit failed meal_id=%s", meal_id)
        await bot_send(
            chat_id=chat_id,
            text=f"⚠️ No se pudo mostrar la actualización de MFP: {type(exc).__name__}",
            bot=bot,
            log_context="mfp_refresh",
        )
    except Exception as exc:
        logger.exception("Hermes MFP refresh reporting failed meal_id=%s", meal_id)
        await bot_send(
            chat_id=chat_id,
            text=f"⚠️ No se pudo completar la actualización de MFP: {type(exc).__name__}",
            bot=bot,
            log_context="mfp_refresh",
        )

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
        dual_info = None
        callback_later_u = None
        callback_duration_min = None

        if data.startswith("accept_manual|"):
            # accept_manual|units|uuid
            parts = data.split("|")
            units_override = float(parts[1])
            request_id = parts[2]
            is_accept = True
            
        elif data.startswith("accept_dual|"):
            # accept_dual|request_id|now_u|later_u|later_after_min
            parts = data.split("|")
            request_id = parts[1]
            now_u = float(parts[2])
            later_u = float(parts[3])
            
            units_override = now_u
            callback_later_u = later_u
            # Keep callbacks sent before the delay field was added working.
            callback_duration_min = int(parts[4]) if len(parts) > 4 else 120
            dual_info = f" (Dual: {now_u} + {later_u} ext)"
            is_accept = True
            
        elif "|" in data:
            action_prefix, request_id = data.split("|", 1)
            is_accept = (action_prefix == "accept" or action_prefix == "accept_manual")
        else:
            # Legacy fallback
            request_id = data.split("_")[-1]
            is_accept = "accept_bolus_" in data

        snapshot = _get_snapshot_store().get(request_id)
        
        if not snapshot:
            # Try looking up by full data just in case it was stored weirdly
            snapshot = _get_snapshot_store().get(data)
        
        if not snapshot:
            logger.warning(f"Snapshot missing for req={request_id}. Available count={len(_get_snapshot_store())}")
            
            # --- Active Plan Recovery Logic ---
            if is_accept and units_override is not None:
                # Reconstruct minimal snapshot for "manual" acceptance (e.g. Active Plan Reminder)
                snapshot = {
                    "carbs": 0,
                    "fat": 0, 
                    "protein": 0,
                    "fiber": 0,
                    "notes": "Recordatorio",
                    "source": "ActivePlan",
                    "units": units_override,
                }
                logger.info(f"Synthesized snapshot for manual accept: {units_override} U")
            elif not is_accept:
                # If cancelling a missing snapshot (likely Active Plan that wasn't stored in RAM), just confirm cancel
                await edit_message_text_safe(query, "❌ Descartado.")
                return
            else:
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
             
             _get_snapshot_store().pop(request_id, None)
             if origin_id:
                  from app.services.companion_service import resolve_episode_by_fingerprint
                  async with SessionLocal() as session:
                       await resolve_episode_by_fingerprint(
                           snapshot.get("user_id") or config.get_bot_default_username(),
                           f"meal_detected:{snapshot.get('episode_origin_id') or origin_id}",
                           session,
                       )
             return
            
        rec = snapshot.get("rec")
        snapshot_imported_meal_id = snapshot.get("imported_meal_id")
        snapshot_imported_fingerprint = snapshot.get("imported_meal_fingerprint")
        snapshot_imported_version = snapshot.get("imported_meal_version")
        if snapshot_imported_meal_id and snapshot_imported_fingerprint:
            from app.models.imported_meal import ImportedMeal

            async with SessionLocal() as session:
                current_imported_meal = await session.get(
                    ImportedMeal, snapshot_imported_meal_id
                )
            if (
                current_imported_meal is None
                or current_imported_meal.fingerprint != snapshot_imported_fingerprint
                or (
                    snapshot_imported_version is not None
                    and current_imported_meal.version != snapshot_imported_version
                )
            ):
                _get_snapshot_store().pop(request_id, None)
                if current_imported_meal is None:
                    stale_text, stale_markup = (
                        "⚠️ La comida ya no está disponible. No se ha registrado insulina.",
                        None,
                    )
                else:
                    latest_text, stale_markup = _imported_meal_review_card(
                        current_imported_meal
                    )
                    stale_text = (
                        "⚠️ La comida cambió después de este cálculo. No se ha "
                        "registrado insulina; revisa la versión actual.\n\n" + latest_text
                    )
                await edit_message_text_safe(
                    query, stale_text, reply_markup=stale_markup
                )
                return
        if isinstance(rec, BolusResponseV2):
             carbs = snapshot["carbs"]
             _, recommended_upfront, rec_later_u, rec_duration_min = _resolve_bolus_delivery(rec)
             units = units_override if units_override is not None else recommended_upfront
             planned_later_u = callback_later_u if callback_later_u is not None else rec_later_u
             planned_duration_min = callback_duration_min if callback_duration_min is not None else rec_duration_min
        elif "units" in snapshot:
             # AI Router Snapshot
             units = units_override if units_override is not None else snapshot["units"]
             carbs = snapshot.get("carbs", 0)
             planned_later_u = callback_later_u or 0.0
             planned_duration_min = callback_duration_min or 0
        else:
             await edit_message_text_safe(query, "⚠️ Error: Snapshot irreconocible.")
             return

        if units < 0:
             health.record_action(f"callback:accept:{request_id}", False, "negative_dose")
             await query.answer("Error: Dosis negativa")
             await edit_message_text_safe(query, "⛔ Error: Dosis negativa.")
             return

        meal_coverage = snapshot.get("meal_coverage")
        meal_id = snapshot.get("meal_id")
        calculation_id = snapshot.get("calculation_id") or request_id
        coverage_user_id = (
            snapshot.get("user_id") or config.get_bot_default_username() or "admin"
        )
        coverage_reserved = False
        if meal_coverage and meal_id and isinstance(rec, BolusResponseV2):
            from app.services.meal_coverage_service import reserve_confirmation

            async with SessionLocal() as session:
                reservation = await reserve_confirmation(
                    session,
                    user_id=coverage_user_id,
                    external_meal_id=meal_id,
                    expected_revision=meal_coverage["revision"],
                    expected_covered=meal_coverage["covered"],
                    calculation_id=calculation_id,
                )
            if not reservation.ok:
                health.record_action(
                    f"callback:accept:{request_id}", False, reservation.reason
                )
                await edit_message_text_safe(
                    query,
                    "⚠️ La comida o su cobertura ha cambiado desde este cálculo. "
                    "No se ha registrado insulina; usa la recomendación más reciente.",
                )
                return
            coverage_reserved = True

        notes = snapshot.get("notes", "Bolus Bot V2")
        if snapshot.get("source"):
             notes += f" ({snapshot['source']})"
        if dual_info:
             notes += dual_info
        
        fat = snapshot.get("fat", 0.0)
        protein = snapshot.get("protein", 0.0)
        fiber = snapshot.get("fiber", 0.0)
        origin_id = snapshot.get("origin_id")
        
        # Duration Extraction
        duration = 0
        if planned_later_u <= 0 and "rec" in snapshot and hasattr(snapshot["rec"], "duration_min"):
             duration = snapshot["rec"].duration_min or 0
        elif planned_later_u <= 0 and "duration_min" in snapshot:
             duration = snapshot["duration_min"] or 0
        
        # Execute Action. Persist the exact recommendation snapshot when available.
        calculation_trace = None
        if isinstance(rec, BolusResponseV2):
             trace_snapshot, trace_ratios, trace_context = build_bolus_trace(
                 rec,
                 accepted_u=units,
                 source=snapshot.get("source") or "telegram",
             )
             calculation_trace = {
                 "snapshot": trace_snapshot,
                 "applied_ratios": trace_ratios,
                 "context": trace_context,
             }

        coverage_confirmation = None
        deterministic_treatment_id = None
        if coverage_reserved:
             from app.services.meal_coverage_service import (
                 covered_after_confirmation,
                 treatment_id_for_calculation,
             )

             positive_correction_after_iob = max(
                 0.0,
                 float(rec.correction_u or 0)
                 - float(rec.iob_applied_to_correction_u or 0),
             )
             covered_after, coverage_fraction, food_allocated, correction_allocated = (
                 covered_after_confirmation(
                     covered_before=meal_coverage["covered"],
                     delta=meal_coverage["delta"],
                     accepted_u=units,
                     recommended_upfront_u=recommended_upfront,
                     positive_correction_after_iob_u=positive_correction_after_iob,
                     round_step_u=float(rec.used_params.round_step_u or 0.1),
                 )
             )
             deterministic_treatment_id = treatment_id_for_calculation(calculation_id)
             coverage_confirmation = {
                 "schema_version": 1,
                 "meal_id": meal_id,
                 "meal_key": meal_coverage["meal_key"],
                 "meal_revision": meal_coverage["revision"],
                 "revision_number": meal_coverage["revision_number"],
                 "calculation_id": calculation_id,
                 "nutrition_total": meal_coverage["current"],
                 "covered_before": meal_coverage["covered"],
                 "covered_delta": meal_coverage["delta"],
                 "covered_after": covered_after,
                 "coverage_fraction": coverage_fraction,
                 "confirmed_bolus_u": units,
                 "food_bolus_allocated_u": food_allocated,
                 "correction_bolus_allocated_u": correction_allocated,
                 "iob_u": rec.iob_u,
                 "iob_applied_to_correction_u": rec.iob_applied_to_correction_u,
                 "autosens_ratio": rec.used_params.autosens_ratio,
                 "confirmed_at": datetime.now(timezone.utc).isoformat(),
             }
             calculation_trace = calculation_trace or {}
             calculation_trace["meal_coverage"] = coverage_confirmation
             notes += f" #meal:{meal_coverage['meal_key']}"

        add_args = {
             "treatment_id": deterministic_treatment_id,
             "insulin": units, 
             "carbs": carbs, 
             "fat": fat, 
             "protein": protein, 
             "fiber": fiber, 
             "notes": notes, 
             "replace_id": origin_id, 
             "duration": duration,
             "calculation_trace": calculation_trace,
             "glucose": _snapshot_glucose_mgdl(snapshot),
        }
        if coverage_reserved:
             add_args["meal_guard"] = {
                 "user_id": coverage_user_id,
                 "external_meal_id": meal_id,
                 "expected_revision": meal_coverage["revision"],
                 "expected_covered": meal_coverage["covered"],
                 "calculation_id": calculation_id,
             }
        result = await tools.add_treatment(add_args)
        
        base_text = _escape_md_v1(query.message.text if query.message else "")

        if isinstance(result, tools.ToolError) or not getattr(result, "ok", False):
            error_msg = result.message if isinstance(result, tools.ToolError) else (result.ns_error or "Error")
            if coverage_reserved:
                from app.services.meal_coverage_service import release_confirmation

                async with SessionLocal() as session:
                    await release_confirmation(
                        session,
                        user_id=coverage_user_id,
                        external_meal_id=meal_id,
                        calculation_id=calculation_id,
                    )
            health.record_action(f"callback:accept:{request_id}", False, error_msg)
            await edit_message_text_safe(query, text=f"{base_text}\n\n❌ Error: {_escape_md_v1(error_msg)}", parse_mode="Markdown")
            return

        if coverage_reserved and coverage_confirmation:
             from app.services.meal_coverage_service import finalize_confirmation

             async with SessionLocal() as session:
                 finalized = await finalize_confirmation(
                     session,
                     user_id=coverage_user_id,
                     external_meal_id=meal_id,
                     calculation_id=calculation_id,
                     treatment_id=getattr(result, "treatment_id", None)
                     or deterministic_treatment_id,
                     covered_after=coverage_confirmation["covered_after"],
                     confirmed_bolus=units,
                 )
             if not finalized.ok:
                 logger.critical(
                     "meal_coverage_finalize_failed meal_key=%s calculation_id=%s treatment_id=%s reason=%s",
                     meal_coverage["meal_key"],
                     calculation_id,
                     getattr(result, "treatment_id", None),
                     finalized.reason,
                 )
                 await edit_message_text_safe(
                     query,
                     "⚠️ El bolo se ha registrado, pero no se pudo actualizar su cobertura "
                     "de forma segura. No repitas la dosis y revisa el historial.",
                 )
                 return

        imported_meal_id = snapshot.get("imported_meal_id")
        if imported_meal_id:
             from app.models.imported_meal import ImportedMeal
             async with SessionLocal() as session:
                  imported_meal = await session.get(ImportedMeal, imported_meal_id)
                  if imported_meal:
                       imported_meal.treatment_status = "TREATED"
                       imported_meal.linked_bolus_id = getattr(result, "treatment_id", None) or deterministic_treatment_id
                       imported_meal.last_bolus_units = units
                       imported_meal.last_bolus_at = datetime.now(timezone.utc)
                       imported_meal.draft_treatment_id = None
                       imported_revision_is_current = bool(
                           imported_meal.fingerprint
                           == snapshot.get("imported_meal_fingerprint")
                           and imported_meal.version
                           == snapshot.get("imported_meal_version")
                       )
                       imported_meal.status = (
                           "CONFIRMED" if imported_revision_is_current
                           else "UPDATED_TREATED"
                       )
                       if imported_revision_is_current:
                           imported_meal.confirmed_at = datetime.now(timezone.utc)
                       session.add(imported_meal)
                       await session.commit()

        if isinstance(rec, BolusResponseV2) and planned_later_u > 0:
             try:
                  plan = _build_bot_active_plan(
                      rec,
                      treatment_id=getattr(result, "treatment_id", None),
                      accepted_upfront_u=units,
                      snapshot=snapshot,
                      later_u_override=planned_later_u,
                      duration_min_override=planned_duration_min,
                  )
                  if plan:
                      settings = get_settings()
                      plan_store = DataStore(Path(settings.data.data_dir))
                      _persist_bot_active_plan(plan_store, plan)
             except Exception as exc:
                  logger.warning("Failed to persist Telegram dual plan: %s", exc)

        if origin_id:
             from app.services.companion_service import resolve_episode_by_fingerprint
             async with SessionLocal() as session:
                  await resolve_episode_by_fingerprint(
                      snapshot.get("user_id") or config.get_bot_default_username(),
                      f"meal_detected:{snapshot.get('episode_origin_id') or origin_id}",
                      session,
                  )

        success_msg = f"{base_text}\n\nRegistrado ✅ {units} U"
        if dual_info: success_msg += dual_info
        if carbs > 0: success_msg += f" / {carbs} g"
        if fiber > 0: success_msg += f" (Fibra: {fiber} g)"
        
        if getattr(result, "injection_site", None):
             site = result.injection_site
             success_msg += f"\n\n📍 Rotado. Siguiente: {_escape_md_v1(site.get('name'))} {site.get('emoji')}"
             
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
                         await query.get_bot().send_photo(chat_id=query.message.chat_id, photo=img_bytes)
                     else:
                         # Fallback to static
                         img_path = base_dir / site["image"]
                         logger.info(f"Fallback to static image: {img_path}")
                         if img_path.exists():
                              await query.get_bot().send_photo(chat_id=query.message.chat_id, photo=open(img_path, "rb"))
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
                     success_msg += f"\n\n📍 Rotado. Siguiente: {_escape_md_v1(new_next['name'])} {new_next['emoji']}"
             except Exception as e:
                 logger.error(f"Failed to auto-rotate injection site: {e}")

        # New Buttons
        kb_post = []
        if result.treatment_id:
             kb_post.append([
                 InlineKeyboardButton("✏️ Renombrar", callback_data=f"rename_txn|{result.treatment_id}"),
                 InlineKeyboardButton("⭐ Guardar Plato", callback_data=f"save_fav_txn|{result.treatment_id}")
             ])

        await edit_message_text_safe(query, text=success_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_post) if kb_post else None)
        _get_snapshot_store().pop(request_id, None)
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

    # --- Imported MyFitnessPal meal review (calculation starts only on Confirm) ---
    if data.startswith("im_"):
        from app.models.imported_meal import ImportedMeal
        from app.services.imported_meal_service import delete_food, discard_meal, resolve_source_conflict

        parts = data.split("|")
        action = parts[0]
        meal_id = parts[1] if len(parts) > 1 else ""
        try:
            if action in {"im_use_mfp", "im_keep"}:
                async with SessionLocal() as session:
                    meal = await session.get(ImportedMeal, meal_id)
                    text_value, markup = _imported_meal_review_card(meal)
                await edit_message_text_safe(
                    query,
                    "⚠️ Esta tarjeta es anterior al control de versiones. "
                    "Revisa de nuevo la versión actual.\n\n" + text_value,
                    reply_markup=markup,
                )
                return

            if action in {"im_u", "im_k"}:
                try:
                    meal_id = str(uuid.UUID(meal_id))
                except (ValueError, AttributeError):
                    raise ValueError("Identificador de comida no válido")
                expected_pending_fingerprint = parts[2] if len(parts) > 2 else ""
                expected_version = int(parts[3]) if len(parts) > 3 else -1
                async with SessionLocal() as session:
                    try:
                        meal = await resolve_source_conflict(
                            session,
                            meal_id=meal_id,
                            use_source=action == "im_u",
                            expected_pending_fingerprint=expected_pending_fingerprint,
                            expected_version=expected_version,
                        )
                    except ValueError as exc:
                        if str(exc) != "source_conflict_changed":
                            raise
                        await session.rollback()
                        meal = await session.get(ImportedMeal, meal_id)
                        text_value, markup = _imported_meal_review_card(meal)
                        await edit_message_text_safe(
                            query,
                            "⚠️ MyFitnessPal volvió a cambiar. La acción anterior "
                            "no se ha aplicado; revisa esta versión.\n\n" + text_value,
                            reply_markup=markup,
                        )
                        return
                    await _sync_imported_meal_draft(session, meal)
                    await session.commit()
                    text_value, markup = _imported_meal_review_card(meal)
                await edit_message_text_safe(query, text_value, reply_markup=markup)
                return

            if action == "im_diff":
                async with SessionLocal() as session:
                    meal = await session.get(ImportedMeal, meal_id)
                    pending = dict(meal.pending_source_version or {})
                current_by_name = {str(food.get("name")): float(food.get("carbs_g") or 0) for food in meal.foods}
                pending_by_name = {str(food.get("name")): float(food.get("carbs_g") or 0) for food in pending.get("foods") or []}
                names = sorted(set(current_by_name) | set(pending_by_name))
                lines = ["Cambios MFP ↔ versión revisada", ""]
                for name in names:
                    old, new = current_by_name.get(name), pending_by_name.get(name)
                    if old != new:
                        lines.append(f"• {name}: {old if old is not None else '—'} → {new if new is not None else '—'} g HC")
                compact_meal_id = str(meal.id).replace("-", "")
                pending_token = str(pending.get("fingerprint") or "")[:16]
                suffix = f"{compact_meal_id}|{pending_token}|{meal.version}"
                buttons = [[InlineKeyboardButton("Usar MFP", callback_data=f"im_u|{suffix}"), InlineKeyboardButton("Mantener revisada", callback_data=f"im_k|{suffix}")]]
                await edit_message_text_safe(query, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))
                return

            if action == "im_confirm":
                async with SessionLocal() as session:
                    meal = await session.get(ImportedMeal, meal_id)
                    if meal is None:
                        raise ValueError("No encuentro la comida")
                    if not meal.is_stable or meal.validation_error:
                        await query.answer("Comida no validada: cálculo bloqueado", show_alert=True)
                        return
                    if meal.discarded_fingerprint == meal.fingerprint:
                        await query.answer("Esta versión está descartada", show_alert=True)
                        return
                    await _sync_imported_meal_draft(session, meal)
                    await session.commit()
                    values = {
                        "carbs": meal.calculated_carbs, "fat": meal.fat,
                        "protein": meal.protein, "fiber": meal.fiber,
                        "source": f"MyFitnessPal revisado ({meal.user_id})",
                        "origin_id": meal.draft_treatment_id,
                        "meal_id": meal.source_reference,
                        "meal_user_id": meal.user_id,
                        "imported_meal_id": meal.id,
                        "meal_slot": meal.meal_type,
                        "fingerprint": meal.fingerprint,
                        "version": meal.version,
                    }
                await edit_message_text_safe(query, "✅ Comida confirmada. Calculando con glucosa e IOB actuales…")
                try:
                    calculation_delivery = await on_new_meal_received(
                        values["carbs"], values["fat"], values["protein"], values["fiber"],
                        values["source"], origin_id=values["origin_id"], meal_id=values["meal_id"],
                        meal_user_id=values["meal_user_id"], imported_meal_id=values["imported_meal_id"],
                        imported_meal_fingerprint=values["fingerprint"],
                        imported_meal_version=values["version"],
                        meal_slot=values["meal_slot"],
                        edit_message_id=query.message.message_id, skip_duplicate_checks=True,
                    )
                except Exception:
                    logger.exception("Imported meal calculation failed meal_id=%s", meal_id)
                    calculation_delivery = None
                if getattr(calculation_delivery, "status", None) == "sent":
                    async with SessionLocal() as session:
                        confirmed_meal = await session.get(ImportedMeal, meal_id)
                        revision_is_current = bool(
                            confirmed_meal
                            and confirmed_meal.fingerprint == values["fingerprint"]
                            and confirmed_meal.version == values["version"]
                        )
                        if revision_is_current:
                            confirmed_meal.status = "CONFIRMED"
                            confirmed_meal.confirmed_at = datetime.now(timezone.utc)
                            session.add(confirmed_meal)
                            await session.commit()
                        elif confirmed_meal is not None:
                            latest_text, latest_markup = _imported_meal_review_card(
                                confirmed_meal
                            )
                        else:
                            latest_text, latest_markup = (
                                "⚠️ La comida ya no está disponible.",
                                None,
                            )
                    if revision_is_current:
                        return
                    snapshot_store = _get_snapshot_store()
                    for snapshot_key in list(snapshot_store.keys()):
                        stale_snapshot = snapshot_store.get(snapshot_key) or {}
                        if (
                            stale_snapshot.get("imported_meal_id") == meal_id
                            and stale_snapshot.get("imported_meal_fingerprint") == values["fingerprint"]
                            and stale_snapshot.get("imported_meal_version") == values["version"]
                        ):
                            snapshot_store.pop(snapshot_key, None)
                    await edit_message_text_safe(
                        query,
                        "⚠️ MyFitnessPal cambió la comida durante el cálculo. "
                        "La recomendación anterior ha quedado anulada.\n\n" + latest_text,
                        reply_markup=latest_markup,
                    )
                    return

                async with SessionLocal() as session:
                    retry_meal = await session.get(ImportedMeal, meal_id)
                    if retry_meal is not None:
                        retry_text, retry_markup = _imported_meal_review_card(retry_meal)
                    else:
                        retry_text, retry_markup = (
                            "⚠️ No se ha podido recuperar la comida para reintentar.",
                            None,
                        )
                await edit_message_text_safe(
                    query,
                    "⚠️ No se ha podido preparar una recomendación segura. "
                    "No se ha registrado ningún bolo. Puedes reintentarlo.\n\n"
                    + retry_text,
                    reply_markup=retry_markup,
                )
                return

            if action == "im_edit":
                async with SessionLocal() as session:
                    meal = await session.get(ImportedMeal, meal_id)
                    if meal is None:
                        raise ValueError("No encuentro la comida")
                    buttons = [
                        [InlineKeyboardButton(f"{i + 1} · {food.get('name')} · {float(food.get('carbs_g') or 0):g} g", callback_data=f"im_food|{meal.id}|{i}")]
                        for i, food in enumerate(meal.foods)
                    ]
                    buttons.extend([
                        [InlineKeyboardButton("➕ Añadir", callback_data=f"im_add|{meal.id}")],
                        [InlineKeyboardButton("↩️ Volver", callback_data=f"im_back|{meal.id}")],
                    ])
                await edit_message_text_safe(query, "✏️ Editar alimentos\n\nSelecciona uno:", reply_markup=InlineKeyboardMarkup(buttons))
                return

            if action == "im_food":
                index = int(parts[2])
                async with SessionLocal() as session:
                    meal = await session.get(ImportedMeal, meal_id)
                    food = meal.foods[index]
                text_value = f"{food.get('name')}\n{food.get('quantity') or ''} {food.get('unit') or ''}\n{float(food.get('carbs_g') or 0):g} g HC"
                buttons = [
                    [InlineKeyboardButton("✏️ Cantidad", callback_data=f"im_qty|{meal_id}|{index}"), InlineKeyboardButton("✏️ HC", callback_data=f"im_carbs|{meal_id}|{index}")],
                    [InlineKeyboardButton("🗑 Eliminar", callback_data=f"im_del|{meal_id}|{index}")],
                    [InlineKeyboardButton("↩️ Volver", callback_data=f"im_edit|{meal_id}")],
                ]
                await edit_message_text_safe(query, text_value, reply_markup=InlineKeyboardMarkup(buttons))
                return

            if action in {"im_carbs", "im_qty"}:
                index = int(parts[2])
                async with SessionLocal() as session:
                    meal = await session.get(ImportedMeal, meal_id)
                    food = meal.foods[index]
                context.user_data["imported_meal_edit"] = {
                    "step": "carbs" if action == "im_carbs" else "quantity",
                    "meal_id": meal_id, "index": index,
                }
                prompt = (
                    f"Introduce los HC correctos para:\n\n{food.get('name')}\nActual: {float(food.get('carbs_g') or 0):g} g"
                    if action == "im_carbs" else f"Introduce la cantidad correcta para:\n\n{food.get('name')}\nActual: {food.get('quantity') or '-'} {food.get('unit') or ''}"
                )
                await edit_message_text_safe(query, prompt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Volver", callback_data=f"im_edit|{meal_id}")]]))
                return

            if action == "im_add":
                context.user_data["imported_meal_edit"] = {"step": "add_name", "meal_id": meal_id}
                await edit_message_text_safe(query, "Nombre del alimento:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Volver", callback_data=f"im_edit|{meal_id}")]]))
                return

            if action == "im_del":
                index = int(parts[2])
                async with SessionLocal() as session:
                    meal = await session.get(ImportedMeal, meal_id)
                    food = meal.foods[index]
                buttons = [[InlineKeyboardButton("✅ Eliminar", callback_data=f"im_del_yes|{meal_id}|{index}")], [InlineKeyboardButton("↩️ Cancelar", callback_data=f"im_food|{meal_id}|{index}")]]
                await edit_message_text_safe(query, f"¿Eliminar “{food.get('name')} · {float(food.get('carbs_g') or 0):g} g HC”?", reply_markup=InlineKeyboardMarkup(buttons))
                return

            if action == "im_del_yes":
                async with SessionLocal() as session:
                    meal = await delete_food(session, meal_id=meal_id, index=int(parts[2]))
                    await _sync_imported_meal_draft(session, meal)
                    await session.commit()
                    text_value, markup = _imported_meal_review_card(meal)
                await edit_message_text_safe(query, text_value, reply_markup=markup)
                return

            if action == "im_back":
                context.user_data.pop("imported_meal_edit", None)
                async with SessionLocal() as session:
                    meal = await session.get(ImportedMeal, meal_id)
                    text_value, markup = _imported_meal_review_card(meal)
                await edit_message_text_safe(query, text_value, reply_markup=markup)
                return

            if action == "im_discard":
                async with SessionLocal() as session:
                    meal = await discard_meal(session, meal_id=meal_id)
                await edit_message_text_safe(query, "🗑 Comida descartada. Esta misma versión no volverá a aparecer.")
                return

            if action == "im_refresh":
                _, _, configuration_error = _hermes_mfp_refresh_configuration()
                if configuration_error:
                    await bot_send(
                        chat_id=query.message.chat_id,
                        text=f"⚠️ No se pudo actualizar MFP: {configuration_error}",
                        bot=query.get_bot(),
                        log_context="mfp_refresh",
                    )
                    return

                refresh_bot = query.get_bot()
                refresh_chat_id = query.message.chat_id
                refresh_message_id = query.message.message_id
                await edit_message_text_safe(query, f"{query.message.text}\n\n🔄 Actualizando desde MyFitnessPal…")

                asyncio.create_task(
                    _refresh_imported_meal_from_hermes(
                        bot=refresh_bot,
                        chat_id=refresh_chat_id,
                        message_id=refresh_message_id,
                        meal_id=meal_id,
                    ),
                    name=f"mfp-refresh-{meal_id}",
                )
                return
        except Exception as exc:
            logger.exception("Imported meal callback failed")
            await edit_message_text_safe(query, f"⚠️ No se pudo completar la revisión: {exc}")
            return

    # --- Persistent Companion Episode ---
    if data.startswith("companion|"):
        try:
            _, action, episode_id = data.split("|", 2)
            action_map = {"ack": "acknowledge", "snooze": "snooze", "dismiss": "dismiss"}
            if action not in action_map:
                raise ValueError("unknown companion action")
            user_settings, resolved_user_id = await get_bot_user_settings_with_user_id()
            username = _resolve_bolus_user_id(user_settings, resolved_user_id)
            from uuid import UUID
            from app.services.companion_service import act_on_episode
            async with SessionLocal() as session:
                row = await act_on_episode(
                    username, UUID(episode_id), action_map[action], session,
                    snooze_minutes=30,
                )
            suffix = {
                "ack": "✅ Entendido. Seguiré vigilando sin repetir este aviso.",
                "snooze": "🔕 Silenciado 30 minutos.",
                "dismiss": "🗑️ Aviso descartado hasta que la situación se resuelva y vuelva a aparecer.",
            }[action]
            original = query.message.text or row.title
            await edit_message_text_safe(query, f"{original}\n\n{suffix}")
            health.record_action(f"companion:{action}", True)
        except Exception as exc:
            logger.error("Companion callback failed: %s", exc)
            await edit_message_text_safe(query, "No he podido guardar la acción. Inténtalo de nuevo.")
            health.record_action("companion:callback", False, str(exc))
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
            user_settings, resolved_user_id = await get_bot_user_settings_with_user_id()
            username = _resolve_bolus_user_id(user_settings, resolved_user_id)
            
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

    # --- Exercise Flow ---
    if data.startswith("exercise_start|"):
        _, req_id = data.split("|")
        snapshot = _get_snapshot_store().get(req_id)
        if not snapshot:
            await query.answer("Sesión caducada")
            return

        flow = context.user_data.get("exercise_flow")
        if flow and not _exercise_flow_expired(flow):
            if flow.get("request_id") != req_id:
                await query.answer("Ya hay un ejercicio en curso.")
                return
        context.user_data["exercise_flow"] = {
            "request_id": req_id,
            "step": "level",
            "created_at": time.time(),
        }

        keyboard = [
            [
                InlineKeyboardButton("Suave", callback_data=f"exercise_level|{req_id}|low"),
                InlineKeyboardButton("Moderado", callback_data=f"exercise_level|{req_id}|moderate"),
                InlineKeyboardButton("Intenso", callback_data=f"exercise_level|{req_id}|high"),
            ],
            [
                InlineKeyboardButton("❌ Cancelar", callback_data=f"exercise_cancel|{req_id}")
            ],
        ]
        await reply_text(
            update,
            context,
            "🏃‍♂️ **Ejercicio**\nSelecciona la intensidad:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if data.startswith("exercise_level|"):
        _, req_id, level = data.split("|")
        flow = context.user_data.get("exercise_flow")
        if not flow or flow.get("request_id") != req_id or _exercise_flow_expired(flow):
            context.user_data.pop("exercise_flow", None)
            await query.answer("Sesión caducada")
            return

        flow["level"] = level
        flow["step"] = "duration"
        flow["created_at"] = time.time()
        context.user_data["exercise_flow"] = flow

        duration_buttons = [
            InlineKeyboardButton(f"{m} min", callback_data=f"exercise_duration|{req_id}|{m}")
            for m in EXERCISE_DURATION_PRESETS
        ]
        keyboard = [duration_buttons[i : i + 2] for i in range(0, len(duration_buttons), 2)]
        keyboard.append([
            InlineKeyboardButton("Otro…", callback_data=f"exercise_other|{req_id}"),
            InlineKeyboardButton("❌ Cancelar", callback_data=f"exercise_cancel|{req_id}"),
        ])

        await reply_text(
            update,
            context,
            "⏱️ **Duración**\nSelecciona los minutos:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if data.startswith("exercise_duration|"):
        _, req_id, minutes_val = data.split("|")
        flow = context.user_data.get("exercise_flow")
        if not flow or flow.get("request_id") != req_id or _exercise_flow_expired(flow):
            context.user_data.pop("exercise_flow", None)
            await query.answer("Sesión caducada")
            return

        if flow.get("step") == "calculating":
            await query.answer("Calculando...")
            return

        try:
            minutes = int(minutes_val)
        except ValueError:
            await query.answer("Minutos inválidos")
            return

        flow["step"] = "calculating"
        context.user_data["exercise_flow"] = flow
        await _apply_exercise_recalculation(
            update,
            context,
            request_id=req_id,
            intensity=flow.get("level", "moderate"),
            minutes=minutes,
            source="preset",
            query=query,
        )
        context.user_data.pop("exercise_flow", None)
        return

    if data.startswith("exercise_other|"):
        _, req_id = data.split("|")
        flow = context.user_data.get("exercise_flow")
        if not flow or flow.get("request_id") != req_id or _exercise_flow_expired(flow):
            context.user_data.pop("exercise_flow", None)
            await query.answer("Sesión caducada")
            return

        flow["step"] = "awaiting_duration"
        flow["created_at"] = time.time()
        context.user_data["exercise_flow"] = flow
        await reply_text(update, context, "✍️ Escribe los minutos de ejercicio (ej. 25):")
        return

    if data.startswith("exercise_cancel|"):
        _, req_id = data.split("|")
        flow = context.user_data.get("exercise_flow")
        if flow and flow.get("request_id") == req_id:
            context.user_data.pop("exercise_flow", None)
        await query.answer("Ejercicio cancelado")
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
    if data.startswith("accept") or data.startswith("cancel|") or data.startswith("edit_dose|") or data.startswith("set_slot|") or data.startswith("edit_macros|"):
        # REMOVED: Early cancel interception that prevented DB cleanup.
        # Flow continues to _handle_snapshot_callback below.
             
        if data.startswith("edit_macros|"):
            try:
                # edit_macros|req_id
                parts = data.split("|")
                req_id = parts[1]
                context.user_data["editing_meal_request"] = req_id
                
                # Fetch snapshot for current values display?
                snap = _get_snapshot_store().get(req_id)
                current_info = ""
                if snap:
                     c = snap.get("carbs", 0)
                     f = snap.get("fat", 0)
                     p = snap.get("protein", 0)
                     current_info = f"\n(Actual: C={c} F={f} P={p})"

                await edit_message_text_safe(query, 
                    text=f"{query.message.text}\n\n✏️ **Editar Nutrientes**{current_info}\nEscribe los nuevos valores en formato: `C F P`\nEjemplo: `50 20 15`",
                    parse_mode="Markdown"
                )
                health.record_action(f"callback:edit_macros:{req_id}", True)
            except Exception as e:
                logger.error(f"Edit macros callback error: {e}")
            return

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
                snapshot = _get_snapshot_store().get(req_id)
                if not snapshot or "rec" not in snapshot:
                    await query.answer("Sesión caducada")
                    return
                
                user_settings, resolved_user_id = await get_bot_user_settings_with_user_id()
                req_v2 = build_slot_recalc_payload(snapshot, slot)

                req_v2.confirm_iob_unknown = True
                req_v2.confirm_iob_stale = True

                new_rec = await _calculate_bolus_with_context(
                    req_v2,
                    user_settings=user_settings,
                    resolved_user_id=resolved_user_id,
                    snapshot_user_id=snapshot.get("user_id"),
                )
                if snapshot.get("user_id") is None and resolved_user_id:
                    snapshot["user_id"] = resolved_user_id
                
                # Update Snapshot
                snapshot["rec"] = new_rec
                snapshot["payload"] = req_v2
                
                # Update Message
                total_u, rec_u, later_u, duration_min = _resolve_bolus_delivery(new_rec)
                lines = []
                lines.append(f"🍽️ **Nueva Comida Detectada** (MFP)")
                lines.append(f"Slot: **{slot.upper()}**")
                lines.append("")
                lines.append(f"Resultado total: **{total_u:g} U**")
                if later_u > 0:
                    lines.append(f"Ahora: **{rec_u:g} U**")
                    lines.append(f"Planificada para revisar tras {duration_min} min: **{later_u:g} U**")
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
                ]
                _maybe_append_exercise_button(keyboard, request_id=req_id, label="🏃 Añadir ejercicio")
                keyboard.append([
                    InlineKeyboardButton("🌅 Desayuno", callback_data=f"set_slot|breakfast|{req_id}"),
                    InlineKeyboardButton("🍕 Comida", callback_data=f"set_slot|lunch|{req_id}"),
                    InlineKeyboardButton("🍽️ Cena", callback_data=f"set_slot|dinner|{req_id}"),
                    InlineKeyboardButton("🥨 Snack", callback_data=f"set_slot|snack|{req_id}"),
                ])
                _log_bolus_keyboard_build(
                    update,
                    request_id=req_id,
                    bolus_mode="simple",
                    keyboard=keyboard,
                )
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
        # Structured plans use plan_id. Historical messages may still carry a
        # treatment id; the store helper accepts either identifier.
        parts = data.split("|")
        action = parts[0]
        identifier = parts[1] if len(parts) > 1 else "unknown"
        settings = get_settings()
        plan_store = DataStore(Path(settings.data.data_dir))
        from app.services.active_plan_store import find_active_plan, update_active_plan

        if action == "combo_review":
             plan = find_active_plan(plan_store, identifier)
             if not plan:
                 await edit_message_text_safe(query, "⚠️ No encuentro el plan activo. Revisa el cálculo desde la app.")
                 health.record_action(f"callback:combo_review:{identifier}", False, "plan_missing")
                 return

             status_res = await tools.execute_tool("get_status_context", {})
             bg = getattr(status_res, "bg_mgdl", None)
             trend = getattr(status_res, "direction", None)
             iob = getattr(status_res, "iob_u", None)
             planned = float(plan.get("later_u_planned") or 0)
             slot = plan.get("meal_slot") or "?"
             review_text = (
                 f"🔎 **Revisión del plan dual**\n\n"
                 f"Pendiente original: **{planned:g} U**\n"
                 f"Franja: **{slot}**\n"
                 f"Glucosa actual: **{bg if bg is not None else '?'}** {trend or ''}\n"
                 f"IOB actual: **{iob if iob is not None else '?'} U**\n\n"
                 "Esto es el plan original, no una nueva recomendación. "
                 "No he registrado ni administrado insulina. Recalcula antes de decidir la dosis final."
             )
             buttons = [
                 [InlineKeyboardButton("⏰ +30 min", callback_data=f"combo_later|{identifier}")],
                 [InlineKeyboardButton("❌ Cancelar plan", callback_data=f"combo_no|{identifier}")],
             ]
             await edit_message_text_safe(query, review_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
             health.record_action(f"callback:combo_review:{identifier}", True)

        elif action == "combo_later":
             snooze_until = int((time.time() + 30 * 60) * 1000)
             updated = update_active_plan(plan_store, identifier, snooze_until_ts=snooze_until)
             if updated:
                 await edit_message_text_safe(query, "⏳ Plan pospuesto 30 min. No se ha registrado insulina.")
                 health.record_action(f"callback:combo_later:{identifier}", True)
             else:
                 await edit_message_text_safe(query, "⏳ Aviso cerrado. El plan estructurado ya no está disponible.")
                 health.record_action(f"callback:combo_later:{identifier}", False, "plan_missing")

        elif action == "combo_no":
             updated = update_active_plan(plan_store, identifier, status="cancelled")
             await edit_message_text_safe(query, "❌ Plan cancelado. No se ha registrado insulina.")
             health.record_action(f"callback:combo_no:{identifier}", bool(updated), None if updated else "plan_missing")

        elif action == "combo_yes":
             # Backward compatibility for already-sent old keyboards. Never claim
             # that a dose was recorded when no treatment write occurred.
             await edit_message_text_safe(
                 query,
                 "⚠️ Este botón antiguo no registra insulina. Abre/recalcula el plan antes de decidir la 2ª parte.",
             )
             health.record_action(f"callback:combo_yes_legacy:{identifier}", True)
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

    if data.startswith("basal_yes"):
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
             
             # Check for passed units in callback
             if "|" in data:
                 try:
                    suggested_u = float(data.split("|")[1])
                 except: pass

             # Auto-detect historical basal if not configured AND no valid override
             if suggested_u == 0.0:
                 try:
                     async with SessionLocal() as session:
                         from sqlalchemy import text as sql_text
                         # Finds last treatment with 'basal' in any form
                         stmt = sql_text("SELECT insulin FROM treatments WHERE (event_type ILIKE '%basal%' OR notes ILIKE '%basal%') AND insulin > 0 ORDER BY created_at DESC LIMIT 1")
                         row = (await session.execute(stmt)).fetchone()
                         if row:
                             suggested_u = float(row.insulin)
                 except Exception as ex:
                     logger.warning(f"Failed to auto-detect basal: {ex}")
             
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
                 user_settings, resolved_user_id = await get_bot_user_settings_with_user_id()
                 username = _resolve_bolus_user_id(user_settings, resolved_user_id)
                 last_basal = await get_latest_basal_dose(username)

                 # Calculate minutes since last basal dose
                 mins_ago = 9999
                 if last_basal and last_basal.get("created_at"):
                     created = last_basal["created_at"]
                     if hasattr(created, 'timestamp'):
                         now_utc = datetime.now(timezone.utc)
                         created_aware = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
                         mins_ago = (now_utc - created_aware).total_seconds() / 60.0

                 if last_basal and mins_ago < 720: # 12 hours
                     logger.warning(f"Guardrail blocked basal: Found one {mins_ago:.0f}m ago")
                     await _update_basal_event("done")
                     health.record_action("basal_guardrail_block", True, f"found_recent_{int(mins_ago)}m")
                     await edit_message_text_safe(query, f"{query.message.text}\n\n⚠️ **Ya registrada**\nHe visto una basal reciente ({int(mins_ago)} min). No la duplico.")
                     return
             except Exception as e:
                 logger.error(f"Basal guardrail check failed: {e}")
                 # Fail safe? Or proceed? Proceeding is risky. Let's warn but proceed if DB error?
                 # Safest is to proceed if we can't verify, BUT log heavily. 
                 # Or better: if checking fails, we shouldn't block user from living.
                 pass

             # Save to basal_dose table (NOT treatments) to avoid IOB contamination
             basal_res = await upsert_basal_dose(
                 user_id=username,
                 dose_u=units,
                 effective_from=date.today(),
                 created_at=datetime.now(timezone.utc)
             )

             if not basal_res:
                 raise Exception("Error guardando dosis basal en DB")

             # Rotate injection site for basal
             rotation_site = None
             try:
                 from app.services.async_injection_manager import AsyncInjectionManager
                 mgr = AsyncInjectionManager(username)
                 rotation_site = await mgr.rotate_site("basal")
             except Exception as rot_e:
                 logger.warning(f"Basal rotation failed: {rot_e}")

             # Mark Done
             await _update_basal_event("done")
             health.record_action("action_basal_register_done", True, f"units={units}")

             success_txt = f"{query.message.text}\n\n✅ Registrada: **{units} U**"

             site = rotation_site
             if site:
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
                p = await _hydrate_bolus_snapshot(p)
                _get_snapshot_store().set(p["id"], p)
            
            if bot_reply.buttons:
                reply_markup = InlineKeyboardMarkup(bot_reply.buttons)
                await reply_text(update, context, bot_reply.text, reply_markup=reply_markup)
            else:
                await reply_text(update, context, bot_reply.text)
                
            context.user_data.pop("pending_voice_text", None)
            
        except Exception as e:
            logger.error(f"Voice confirm processing error: {e}")
            await reply_text(update, context, f"Error procesando voz: {e}")

async def _collect_ml_data():
    try:
        from app.bot.tools import get_status_context
        from app.bot.user_settings_resolver import resolve_bot_user_settings
        
        # 1. Resolve which user we are collecting for
        user_settings, resolved_user = await resolve_bot_user_settings()
        
        status = await get_status_context(username=resolved_user, user_settings=user_settings)
        if hasattr(status, 'type') and status.type == 'tool_error':
            return
            
        if not status.bg_mgdl:
            return

        async with SessionLocal() as session:
             from sqlalchemy import text
             now_ts = datetime.now(timezone.utc)
             minute = (now_ts.minute // 5) * 5
             bucket_ts = now_ts.replace(minute=minute, second=0, microsecond=0).replace(tzinfo=None)
             
             stmt = text('INSERT INTO ml_training_data (feature_time, user_id, sgv, trend, iob, cob, basal_rate, activity_score, notes) '
                        'VALUES (:ts, :uid, :sgv, :trend, :iob, :cob, :bs, :act, :note) ON CONFLICT (feature_time, user_id) DO NOTHING')


             
             await session.execute(stmt, {
                 'ts': bucket_ts, 
                 'uid': resolved_user, 
                 'sgv': status.bg_mgdl, 
                 'trend': str(status.direction or ''), 
                 'iob': status.iob_u or 0.0, 
                 'cob': status.cob_g or 0.0, 
                 'bs': 0.0, 
                 'act': 0.0, 
                 'note': 'auto'
             })
             await session.commit()
             logger.debug(f"ML data point collected for {resolved_user} at {bucket_ts}")
    except Exception as e:
        logger.warning(f"ML collection failed: {e}")
