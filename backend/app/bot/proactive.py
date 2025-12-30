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
from app.bot import tools, context_builder
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
    # 0. Load Config (needed for chat_id resolution)
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        basal_conf = user_settings.bot.proactive.basal
    except Exception as e:
        health.record_action("job:basal", False, error=f"config_load_error: {e}")
        return

    # 1. Resolve Chat ID
    final_chat_id = chat_id or basal_conf.chat_id or await _get_chat_id()
    if not final_chat_id:
        health.record_event("basal", False, "missing_chat_id")
        return

    # 2. Check Cooldown
    if not cooldowns.is_ready("basal", COOLDOWN_MINUTES["basal"] * 60):
        # We still record event? Optional, maybe reduce noise
        health.record_event("basal", False, "cooldown")
        return

    # 3. Get Context (Includes Basal Status)
    # Using the tool ensures we get the full picture consistent with router
    status_res = await tools.execute_tool("get_status_context", {})
    # 3b. Fetch Deep Basal Context directly 
    # (Context builder already does this, but we need direct access to logic states)
    from app.services import basal_context_service
    # Assuming "admin" for now, ideally pass username
    basal_ctx = await basal_context_service.get_basal_status(username, 0) # Offset 0 for now
    try:
        # 4. Cooldown Check
        if not cooldowns.is_ready("basal", COOLDOWN_MINUTES["basal"] * 60):
            health.record_event("basal", False, "cooldown")
            return

        # 5. Context & Data Collection (Pattern B1)
        # Use Tool for standardized context
        status_res = await tools.execute_tool("get_status_context", {})
        if isinstance(status_res, tools.ToolError):
            health.record_event("basal", False, f"error_tool: {status_res.message}")
            return

        # Fetch Logic Data (Last Dose)
        # 3b. Fetch Deep Basal Context directly 
        from app.services import basal_context_service
        basal_ctx = await basal_context_service.get_basal_status(username, 0)
        
        # 4. Logic Branching
        status = basal_ctx.status
        
        if status == "taken_today":
            health.record_event("basal", False, "already_taken")
            return

        if status == "not_due_yet":
            health.record_event("basal", False, "not_due_yet")
            return
            
        if status == "due_soon":
            health.record_event("basal", False, "due_soon_silent")
            return
        
        if status == "insufficient_history":
            if not basal_conf.time_local:
                 health.record_event("basal", False, "insufficient_history_no_manual")
                 return
            health.record_event("basal", False, "skipped_insufficient_history")
            return

        if status != "late":
            health.record_event("basal", False, f"status_{status}")
            return

        # 5. Prepare Payload for Router
        payload = {
            "basal_status": basal_ctx.to_dict(),
            "bg": getattr(status_res, "bg_mgdl", None),
            "trend": getattr(status_res, "direction", None)
        }

        # 6. Delegate to Router
        from app.bot.llm import router

        reply = await router.handle_event(
            username=username,
            chat_id=final_chat_id,
            event_type="basal", 
            payload=payload
        )
        
        if reply and reply.text:
            # Mark sent only if we really send
            from app.bot.proactive_rules import mark_event_sent
            mark_event_sent("basal")
            
            keyboard = [
                [InlineKeyboardButton("✅ Ya me la puse", callback_data="basal_ack_yes")],
                [InlineKeyboardButton("⏰ +15 min", callback_data="basal_ack_later")],
            ]
            await _send(
                None,
                final_chat_id,
                reply.text,
                log_context="proactive_basal",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            health.record_event("basal", True, "sent_late_reminder")
        else:
            health.record_event("basal", False, "router_silenced")

    except Exception as exc:
        logger.error("Basal reminder failed: %s", exc)
        health.record_action("job:basal", False, error=str(exc))
        try:
            health.set_error(f"Basal reminder failed: {exc}")
        except Exception:
            pass


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
            health.record_event("premeal", False, f"error_tool: {status_res.message}")
            return
            
    except Exception as e:
        logger.error(f"Premeal check failed: {e}")
        health.record_event("premeal", False, f"error_tool: {e}")
        return

    # Robust Data Extraction
    # Convert Pydantic to dict for safe access and aliasing
    stats_dict = {}
    if hasattr(status_res, "model_dump"):
        stats_dict = status_res.model_dump()
    elif hasattr(status_res, "dict"):
        stats_dict = status_res.dict()
    elif isinstance(status_res, dict):
        stats_dict = status_res
    else:
        # Fallback attribute access
        stats_dict = {
            "bg_mgdl": getattr(status_res, "bg_mgdl", None),
            "sgv": getattr(status_res, "sgv", None),
            "delta": getattr(status_res, "delta", None),
            "direction": getattr(status_res, "direction", None)
        }

    # Normalize fields
    bg = stats_dict.get("bg_mgdl")
    if bg is None:
        bg = stats_dict.get("sgv") # Compat fallback
        
    delta = stats_dict.get("delta")
    direction = stats_dict.get("direction")
    
    # Observability
    logger.info(f"[PREMEAL] bg={bg} delta={delta} direction={direction}")

    # SAFETY: Check for missing data
    if bg is None:
         logger.warning(f"[PREMEAL] missing bg in status_context keys={list(stats_dict.keys())}")
         health.record_event("premeal", False, "skipped_missing_bg")
         return

    # Heuristic
    # Explicitly handle None delta
    delta_val = delta if delta is not None else 0
    bg_val = float(bg)
    
    if bg_val < 140 or delta_val < 2:
        health.record_event("premeal", False, "heuristic_low_bg")
        return
        
    payload = {"bg": bg_val, "trend": direction, "delta": delta_val}

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
