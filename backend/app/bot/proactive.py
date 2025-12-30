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

    except Exception as exc:
        logger.error("Basal reminder failed: %s", exc)
        health.record_action("job:basal", False, error=str(exc))
        try:
            health.set_error(f"Basal reminder failed: {exc}")
        except Exception:
            pass


async def premeal_nudge(username: str = "admin", chat_id: Optional[int] = None, trigger: str = "auto") -> None:
    # Resolve default user
    if username == "admin":
        from app.core import config
        username = config.get_bot_default_username()

    # 1. Load Config (for thresholds)
    try:
        from app.bot import tools
        # Load settings for this user (with DB overlay if available)
        user_settings = await tools._load_user_settings(username)
        premeal_conf = user_settings.bot.proactive.premeal
    except Exception as e:
        logger.error(f"Premeal config load failed: {e}")
        health.record_event("premeal", False, f"config_error: {e}")
        return

    # 2. Check Enabled (Config)
    if not premeal_conf.enabled and trigger == "auto":
        # Allow manual run even if disabled? Usually yes for testing, but let's stick to user intent.
        # If manual, we bypass "enabled" check? Maybe useful for diagnostics.
        # But 'enabled' usually means 'system active'.
        # Let's say manual overrides enabled.
        pass
    elif not premeal_conf.enabled:
        return

    # 3. Resolve Chat ID (Config Priority)
    chat_id = chat_id or premeal_conf.chat_id or await _get_chat_id()
    if not chat_id:
        return

    # 4. Check Cooldown (Dynamic from Config)
    # If TRIGGER is manual, bypass cooldown?
    if trigger == "auto":
        silence_sec = premeal_conf.silence_minutes * 60
        if not cooldowns.is_ready("premeal", silence_sec):
            health.record_event("premeal", False, f"silenced_recent(premeal,{premeal_conf.silence_minutes}m)")
            return
        
    # 5. Fetch Context (Tool)
    try:
        status_res = await tools.execute_tool("get_status_context", {"username": username})
        if isinstance(status_res, tools.ToolError):
            health.record_event("premeal", False, f"error_tool: {status_res.message}")
            return  
    except Exception as e:
        logger.error(f"Premeal check failed: {e}")
        health.record_event("premeal", False, f"error_tool: {e}")
        return

    # 6. Data Extraction
    stats_dict = {}
    if hasattr(status_res, "model_dump"): stats_dict = status_res.model_dump()
    elif hasattr(status_res, "dict"): stats_dict = status_res.dict()
    elif isinstance(status_res, dict): stats_dict = status_res
    else:
        stats_dict = {
            "bg_mgdl": getattr(status_res, "bg_mgdl", None),
            "sgv": getattr(status_res, "sgv", None),
            "delta": getattr(status_res, "delta", None),
            "direction": getattr(status_res, "direction", None)
        }

    bg = stats_dict.get("bg_mgdl") or stats_dict.get("sgv")
    delta = stats_dict.get("delta")
    direction = stats_dict.get("direction")
    
    logger.info(f"[PREMEAL] username={username} bg={bg} delta={delta} direction={direction} trigger={trigger}")

    if bg is None:
         logger.warning(f"[PREMEAL] missing bg keys={list(stats_dict.keys())}")
         health.record_event("premeal", False, "skipped_missing_bg")
         return

    # 7. Heuristic (Configurable Thresholds)
    # If Manual, we might want to bypass thresholds?
    # User says: "/run premeal manual: Sí llega mensaje".
    # Assuming manual bypasses thresholds or at least forces check.
    # But message says "Premeal NO debe preguntar por comida si no hay indicios claros... Mantener la lógica actual de cálculo/contexto".
    # And "Premeal puede enviar mensaje si thresholds se cumplen".
    # So manual just bypasses the "no_meal_intent" silence. It PROBABLY still expects high glucose?
    # Spec: "/run premeal manual: Sí llega mensaje". This implies FORCE send.
    # But usually jobs emulate the check.
    # Let's assume manual SHOULD send even if low BG? Or just bypass windows?
    # "Si NO se cumple ninguna: silenced_no_meal_intent".
    # If it is manual, it fulfills "Existing flag explicitly".
    # But later: "Mantener intacta: Lógica de thresholds".
    # So if BG is low, it still returns "heuristic_low_bg".
    # Correct. Manual only bypasses the WINDOW check.

    delta_val = delta if delta is not None else 0
    bg_val = float(bg)
    
    th_bg = premeal_conf.bg_threshold_mgdl
    th_delta = premeal_conf.delta_threshold_mgdl
    
    # We apply thresholds unless manual override of thresholds requested? 
    # For now, apply thresholds as per "Mantener intacta lógica de thresholds".
    # If I run /run premeal and BG is 80, it should probably NOT say "Are you eating?".
    
    if bg_val < th_bg:
        health.record_event("premeal", False, f"heuristic_low_bg(bg={int(bg_val)}<th={th_bg})")
        return

    if delta_val < th_delta:
        health.record_event("premeal", False, f"heuristic_low_delta(delta={delta_val}<th={th_delta})")
        return
        
    payload = {"bg": bg_val, "trend": direction, "delta": delta_val, "trigger": trigger}

    # 8. Delegate to Router
    from app.bot.llm import router

    reply = await router.handle_event(
        username=username,
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
            None, 
            chat_id,
            reply.text,
            log_context="proactive_premeal",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        # Mark sent
        from app.bot.proactive_rules import mark_event_sent
        mark_event_sent("premeal")
        health.record_event("premeal", True, "sent")

async def combo_followup(username: str = "admin", chat_id: Optional[int] = None) -> None:
    # 1. Load User Config (DB Overlay)
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        # Ensure we have the structure, though model_validate usually handles defaults
        if not user_settings.bot.proactive.combo_followup:
             # Fallback if model missing field (should reflect Pydantic default)
             from app.models.settings import ComboFollowupConfig
             conf = ComboFollowupConfig()
        else:
             conf = user_settings.bot.proactive.combo_followup
             
        # Also need global settings for Nightscout Client fallback or data_dir
        global_settings = get_settings()
        
    except Exception as e:
        logger.error(f"Combo config load failed: {e}")
        health.record_event("combo_followup", False, f"config_load_err: {e}")
        return

    # Helper to route safely at exit
    from app.bot.llm import router
    
    async def _route(payload_inner: dict):
        # Resolve chat_id if not present (though we expect final_chat_id to be set by caller time)
        # Use final_chat_id from outer scope which is set before this is called
        cid = final_chat_id 
        if not cid:
             return

        reply = await router.handle_event(
            username=username,
            chat_id=cid,
            event_type="combo_followup",
            payload=payload_inner
        )
        
        if reply and reply.text:
            # Mark asked in DataStore (Persistence)
            # 'store' and 'events' are captured from outer scope
            events.append({
                 "type": "combo_followup_record",
                 "treatment_id": payload_inner.get("treatment_id"),
                 "status": "asked",
                 "asked_at": datetime.now(timezone.utc).isoformat()
            })
            store.save_events(events)
            
            # Send Message
            from telegram import InlineKeyboardMarkup
            await _send(
                None, 
                cid,
                reply.text,
                log_context="proactive_combo",
                reply_markup=InlineKeyboardMarkup(reply.buttons) if reply.buttons else None,
            )

    # 2. Config Check
    if not conf.enabled:
        await _route({"reason_hint": "heuristic_disabled"})
        return

    # Resolve Chat ID
    final_chat_id = chat_id or await _get_chat_id()
    if not final_chat_id:
        return

    # 3. Check Silence (Rules)
    # We pass explicit reason if needed, but Router also does cooldown check.
    # We check Quiet Hours here if specific to combo.
    from app.bot.proactive_rules import check_silence
    # Note: check_silence reads Global Settings for quiet hours currently.
    # We should trust UserSettings 'conf' here.
    
    if conf.quiet_hours_start and conf.quiet_hours_end:
        from app.bot.proactive_rules import _is_quiet_hours
        if _is_quiet_hours(conf.quiet_hours_start, conf.quiet_hours_end):
             await _route({"reason_hint": "silenced_quiet_hours(combo_followup)"})
             return

    # 4. Fetch Treatments
    # Use UserSettings NS config first, then Global
    ns_url = user_settings.nightscout.url or global_settings.nightscout.base_url
    # Note: UserSettings token is usually api_secret, global is token.
    ns_token = user_settings.nightscout.token or global_settings.nightscout.token
    
    if not ns_url:
         await _route({"reason_hint": "missing_ns_config"})
         return
         
    client = NightscoutClient(str(ns_url), ns_token)
    treatments = []
    fetch_error = None
    try:
        treatments = await client.get_recent_treatments(hours=conf.window_hours)
    except Exception as e:
        logger.error(f"Combo check NS error: {e}")
        fetch_error = str(e)
    finally:
        await client.aclose()
        
    if fetch_error:
        await _route({"reason_hint": f"ns_error: {fetch_error}"})
        return

    # 5. Find Candidate
    treatments.sort(key=lambda x: x.created_at, reverse=True)
    candidate = None
    for t in treatments:
        if (t.insulin and t.insulin > 0) or t.eventType in ("Meal Bolus", "Correction Bolus", "Bolus"):
            candidate = t
            break
            
    if not candidate:
        await _route({"reason_hint": "heuristic_no_candidate_bolus"})
        return

    # 6. Check Persistence
    store = DataStore(Path(global_settings.data.data_dir))
    events = store.load_events()
    tid = candidate.id
    if not tid:
         await _route({"reason_hint": "heuristic_no_treatment_id"})
         return

    previous_record = next((e for e in events if e.get("treatment_id") == tid and e.get("type") == "combo_followup_record"), None)
    
    if previous_record:
        status = previous_record.get("status")
        should_skip = True
        
        if status == "snoozed":
             snooze_str = previous_record.get("snooze_until")
             if snooze_str:
                 try:
                     sno = datetime.fromisoformat(snooze_str)
                     if sno.tzinfo is None: sno = sno.replace(tzinfo=timezone.utc)
                     if datetime.now(timezone.utc) >= sno:
                         should_skip = False 
                 except: pass
        
        if should_skip:
            await _route({"reason_hint": "heuristic_already_followed_up"})
            return

    # 7. Check Time
    now_utc = datetime.now(timezone.utc)
    ts = candidate.created_at
    if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
    
    diff_min = (now_utc - ts).total_seconds() / 60
    
    if diff_min < conf.delay_minutes:
         await _route({
             "reason_hint": f"heuristic_too_soon(minutes_since={int(diff_min)}, delay={conf.delay_minutes})",
             "minutes_since": int(diff_min),
             "delay_minutes": conf.delay_minutes
         })
         return

    # 8. Success: Candidate Eligible
    # Do NOT send message yet. Log as eligible_candidate.
    payload = {
        "reason_hint": "eligible_candidate",
        "treatment_id": tid,
        "bolus_units": candidate.insulin,
        "bolus_at": ts.isoformat(),
        "minutes_since": int(diff_min),
        "delay_minutes": conf.delay_minutes
    }
    
    await _route(payload)
    # End here. No message sent. No buttons.


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
