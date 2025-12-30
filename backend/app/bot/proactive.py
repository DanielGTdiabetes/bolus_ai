from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from app.bot.state import cooldowns, health
from app.core import config
from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.services.iob import compute_iob_from_sources
from app.services.bolus import recommend_bolus, BolusRequestData
from app.services.basal_repo import get_latest_basal_dose
from app.services.nightscout_secrets_service import get_ns_config
from app.services.nightscout_secrets_service import get_ns_config
from app.bot import tools
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

COOLDOWN_MINUTES = {
    "basal": 45,
    "premeal": 60,
    "combo": 45,
    "morning": 720,
}


async def _get_chat_id() -> Optional[int]:
    return config.get_allowed_telegram_user_id()


async def _send(bot, chat_id: int, text: str, *, log_context: str, **kwargs):
    from app.bot.service import bot_send

    await bot_send(chat_id=chat_id, text=text, bot=bot, log_context=log_context, **kwargs)


# Removed _get_ns_client dependent on DB



async def basal_reminder(username: str = "admin", chat_id: Optional[int] = None) -> None:
    # 1. Resolve Chat ID
    if chat_id is None:
        chat_id = await _get_chat_id()
    
    if not chat_id:
        return
        
    try:
        if not cooldowns.is_ready("basal", COOLDOWN_MINUTES["basal"] * 60):
            health.record_event("basal_reminder", False, "cooldown")
            return

        # No local DB check for basal. Delegate to Router.
        # Router will see "recent_treatments" in context.
        # If basal is missing from context, LLM might ask.
        # To strictly filter "already done", we'd need a tool "get_last_basal".
        # For now, we trust the LLM prompt "Si usuario ya sabe esto... SKIP" 
        # (though LLM needs data to know).
        # We proceed to invoke router.

        
        # Lazy import
        from app.bot.llm import router

        # LLM ROUTING
        reply = await router.handle_event(
            username="admin", 
            chat_id=chat_id, 
            event_type="basal_reminder", 
            payload={} # Let context builder fill details
        )
        
        if reply and reply.text:
            keyboard = [
                [InlineKeyboardButton("✅ Sí, ya puesta", callback_data="basal_ack_yes")],
                [InlineKeyboardButton("⏰ En 15 min", callback_data="basal_ack_later")],
                [InlineKeyboardButton("🙈 Ignorar", callback_data="ignore")],
            ]
            await _send(
                bot,
                chat_id,
                reply.text,
                log_context="proactive_basal",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
    except Exception as exc:
        logger.error("Basal reminder failed: %s", exc)
        try:
            health.set_error(f"Basal reminder failed: {exc}")
        except Exception:
            logger.debug("Unable to record bot health error for basal reminder.")


async def premeal_nudge(username: str = "admin", chat_id: Optional[int] = None) -> None:
    if chat_id is None:
        chat_id = await _get_chat_id()
    if not chat_id:
        return

    if not cooldowns.is_ready("premeal", COOLDOWN_MINUTES["premeal"] * 60):
        health.record_event("premeal", False, "cooldown")
        return
        
    # Use Tool for Context (No DB dependency here)
    try:
        status_res = await tools.execute_tool("get_status_context", {})
        if isinstance(status_res, tools.ToolError):
            return # Fail silently
            
    except Exception as e:
        logger.error(f"Premeal check failed: {e}")
        health.record_event("premeal", False, f"error_tool: {e}")
        return

    # bg_mgdl, delta, direction
    stats = status_res # It's a StatusContext object
    
    # SAFETY: Check for missing data
    if stats.bg_mgdl is None:
         health.record_event("premeal", False, "skipped_missing_bg")
         return

    # Heuristic
    # Explicitly handle None delta
    delta = stats.delta if stats.delta is not None else 0
    
    if stats.bg_mgdl < 140 or delta < 2:
        health.record_event("premeal", False, "heuristic_low_bg")
        return
        
    payload = {"bg": stats.bg_mgdl, "trend": stats.direction, "delta": delta}

    from app.bot.llm import router

    reply = await router.handle_event(
        username="admin",
        chat_id=chat_id,
        event_type="premeal",
        payload=payload
    )

    if reply and reply.text:
        keyboard = [
            [InlineKeyboardButton("✅ Registrar", callback_data="premeal_add")],
            [InlineKeyboardButton("⏳ Luego", callback_data="ignore")],
        ]
        await _send(
            None, # bot resolved internally
            chat_id,
            reply.text,
            log_context="proactive_premeal",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def combo_followup(username: str = "admin", chat_id: Optional[int] = None) -> None:
    if chat_id is None:
        chat_id = await _get_chat_id()
    if not chat_id:
        return
    if not cooldowns.is_ready("combo", COOLDOWN_MINUTES["combo"] * 60):
        health.record_event("combo_followup", False, "cooldown")
        return
    settings = get_settings()
    store = DataStore(Path(settings.data.data_dir))
    events = store.load_events()
    now_utc = datetime.now(timezone.utc)
    
    # Handle potentially naive stored dates gracefully (assume UTC if naive)
    def parse_event_time(ts_str):
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return now_utc + timedelta(days=365) # Filter out invalid

    pending = [e for e in events if e.get("type") == "combo" and parse_event_time(e["notify_at"]) <= now_utc]
    if not pending:
        return
    
    from app.bot.llm import router
    
    reply = await router.handle_event(
        username="admin",
        chat_id=chat_id,
        event_type="combo_followup",
        payload={"pending_events": len(pending)}
    )
    
    if reply and reply.text:
        await _send(
        None,
        chat_id,
        reply.text,
        log_context="proactive_combo",
    )


async def morning_summary(username: str = "admin", chat_id: Optional[int] = None) -> None:
    if chat_id is None:
        chat_id = await _get_chat_id()
    if not chat_id:
        return
    if not cooldowns.is_ready("morning", COOLDOWN_MINUTES["morning"] * 60):
        health.record_event("morning_summary", False, "cooldown")
        return
    # Use Tool
    try:
        res = await tools.execute_tool("get_nightscout_stats", {"range_hours": 8})
        if isinstance(res, tools.ToolError):
            return
    except Exception:
        return

    payload = {
        "tir_percent": int(res.tir_pct),
        "lows_count": res.lows,
        "last_bg": res.last_bg,
        "hours": 8,
        "avg": int(res.avg_bg)
    }
    
    from app.bot.llm import router

    reply = await router.handle_event(
        username="admin",
        chat_id=chat_id,
        event_type="morning_summary",
        payload=payload
    )
    
    if reply and reply.text:
        await _send(None, chat_id, reply.text, log_context="proactive_morning")


async def light_guardian(username: str = "admin", chat_id: Optional[int] = None) -> None:
    """
    Wrapper around existing glucose monitor job using same bot instance.
    """
    try:
        from app.bot.service import run_glucose_monitor_job
        await run_glucose_monitor_job()
    except Exception as exc:
        logger.warning("Guardian job failed: %s", exc)
