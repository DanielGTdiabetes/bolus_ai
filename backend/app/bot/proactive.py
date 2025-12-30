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
    # 0. Load Settings first
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        basal_conf = user_settings.bot.proactive.basal
    except Exception as e:
        health.record_action("job:basal", False, error=f"config_load_error: {e}")
        return

    # 1. Check Enabled
    if not basal_conf.enabled:
        health.record_event("basal", False, "disabled_in_settings")
        return

    # 2. Resolve Chat ID
    # Priority: explicit argument -> config settings -> global env fallback
    final_chat_id = chat_id or basal_conf.chat_id or await _get_chat_id()
    if not final_chat_id:
        health.record_event("basal", False, "missing_chat_id")
        return

    # 3. Check Time Config
    # User Requirement: Must have time configured even if triggered manually
    if not basal_conf.time_local:
        health.record_event("basal", False, "missing_time_config")
        return

    # Track job execution (User Req: last_action_type="job:basal")
    health.record_action("job:basal", True)

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
        last_dose = await get_latest_basal_dose(username)
        
        # User Req: Handle missing data gracefully
        if not last_dose or status_res.bg_mgdl is None:
            # Check if we have expected units to at least give a partial reminder?
            # Req says "Si falta ... reason=skipped_missing_data". 
            # But let's be more specific if NS is down vs No DB history.
            if status_res.bg_mgdl is None:
                 health.record_event("basal", False, "skipped_missing_ns_data")
            else:
                 health.record_event("basal", False, "skipped_no_dose_history")
            return

        # 6. Construct Payload
        # Calculate time since last dose
        now_utc = datetime.now(timezone.utc)
        last_ts = last_dose.get("created_at")
        if last_ts and last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
            
        hours_ago = 999.0
        if last_ts:
            hours_ago = (now_utc - last_ts).total_seconds() / 3600

        payload = {
            "last_dose": {
                "units": last_dose.get("dose_u"),
                "time": last_ts.isoformat() if last_ts else None,
                "hours_ago": round(hours_ago, 2)
            },
            "bg": status_res.bg_mgdl,
            "trend": status_res.direction,
            "delta": status_res.delta,
            "expected_units": basal_conf.expected_units
        }

        # 7. Delegate to Router (User Req: router.handle_event)
        from app.bot.llm import router

        # Router decides "silence" (noise rules) or "send"
        reply = await router.handle_event(
            username=username,
            chat_id=final_chat_id,
            event_type="basal", 
            payload=payload
        )
        
        # 8. Send Reply if any (Botless way)
        if reply and reply.text:
            keyboard = [
                [InlineKeyboardButton("✅ Sí, ya puesta", callback_data="basal_ack_yes")],
                [InlineKeyboardButton("⏰ En 15 min", callback_data="basal_ack_later")],
                [InlineKeyboardButton("🙈 Ignorar", callback_data="ignore")],
            ]
            await _send(
                None, # No direct bot reference
                final_chat_id,
                reply.text,
                log_context="proactive_basal",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

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
