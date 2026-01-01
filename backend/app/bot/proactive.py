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
from app.services.isf_analysis_service import IsfAnalysisService
from app.models.isf import IsfAnalysisResponse
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



async def basal_reminder(username: str = "admin", chat_id: Optional[int] = None, force: bool = False) -> None:
    # 0. Load Config
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        basal_conf = user_settings.bot.proactive.basal
        global_settings = get_settings()
    except Exception as e:
        health.record_action("job:basal", False, error=f"config_load_error: {e}")
        return

    if not user_settings.bot.enabled:
        return

    if not basal_conf.enabled:
        return

    # 1. Resolve Chat ID
    final_chat_id = chat_id or basal_conf.chat_id or await _get_chat_id()
    if not final_chat_id:
        return

    # 2. Prepare Schedules (Multi-dose support)
    schedules = basal_conf.schedule
    # Fallback to legacy single dose if schedule list is empty but time_local exists
    if not schedules and basal_conf.time_local:
        from app.models.settings import BasalScheduleItem
        # Use a stable ID for legacy fallback to avoid resetting status on restarts
        legacy_item = BasalScheduleItem(
            id="legacy_default", 
            name="Basal", 
            time=basal_conf.time_local, 
            units=basal_conf.expected_units or 0.0
        )
        schedules = [legacy_item]
    
    if not schedules:
        return

    # 3. Setup Context
    store = DataStore(Path(global_settings.data.data_dir))
    events = store.load_events()
    
    import zoneinfo
    tz = zoneinfo.ZoneInfo("Europe/Madrid")
    now_local = datetime.now(tz)
    today_str = now_local.strftime("%Y-%m-%d")

    # 4. Iterate Schedules
    for item in schedules:
        # Key: basal_daily_status:{date}:{item.id}
        # For legacy compatibility, if item.id is 'legacy_default', check old key format first?
        # Actually, let's look for specific entry for this item.
        
        entry = next((e for e in events 
                      if e.get("type") == "basal_daily_status" 
                      and e.get("date") == today_str 
                      and e.get("schedule_id") == item.id), None)
        
        # Backward compatibility: look for entry without schedule_id if this is legacy item
        if not entry and item.id == "legacy_default":
             entry = next((e for e in events 
                      if e.get("type") == "basal_daily_status" 
                      and e.get("date") == today_str 
                      and not e.get("schedule_id")), None)

        if entry:
            st = entry.get("status")
            if st in ("done", "dismissed"):
                 continue # This dose is done
            elif st == "snoozed":
                 until_str = entry.get("snooze_until")
                 if until_str:
                     try:
                         until_dt = datetime.fromisoformat(until_str)
                         if datetime.now(timezone.utc) < until_dt:
                             continue # Still snoozed
                     except: pass
        
        # 5. Check Timing (Is it due?)
        try:
            target_h, target_m = map(int, item.time.split(":"))
            target_dt = now_local.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            
            # If target is in future > 30 min, skip (too early)
            # If target is in past, check if "hours_late" logic needed
            diff_min = (now_local - target_dt).total_seconds() / 60.0
            
            # Allow window: from -30 min (early warning) to +X hours (late)
            if not force and diff_min < -30:
                continue # Too early
                
            # If it's effectively "tomorrow" because target is 23:00 and now is 01:00?
            # Complexity: Basal usually same day. If user has 01:00 am basal, 'today_str' matches.
            # If now is 01:00 and target is 01:00, diff is 0.
            
        except ValueError:
            continue

        # 6. Execute Trigger for this Item
        # Prepare payload
        payload = {
            "persistence_status": entry.get("status") if entry else None,
            "today_str": today_str,
            "schedule_id": item.id,
            "schedule_name": item.name,
            "scheduled_time": item.time,
            "expected_units": item.units,
            "hours_late": max(0, diff_min / 60.0)
        }
        
        from app.bot.llm import router
        # We need a unique event_type or handle logic in router?
        # Router 'basal' logic expects single fields. We pass more context.
        reply = await router.handle_event(
            username=username,
            chat_id=final_chat_id,
            event_type="basal", 
            payload=payload
        )
        
        if reply and reply.text:
             # Send message
            from app.bot.service import bot_send
            await bot_send(
                chat_id=final_chat_id, 
                text=reply.text, 
                bot=None, # will resolve global
                log_context=f"proactive_basal_{item.id}",
                reply_markup=InlineKeyboardMarkup(reply.buttons) if reply.buttons else None
            )
            
            # Mark sent & Update Persistence
            from app.bot.proactive_rules import mark_event_sent
            mark_event_sent("basal") # Global anti-spam for type
            
            if not entry:
                events.append({
                    "type": "basal_daily_status",
                    "date": today_str,
                    "schedule_id": item.id,
                    "status": "asked",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                store.save_events(events)
            
            # Return after sending ONE reminder to avoid spamming multiple at once?
            # Yes, let's handle one at a time per check interval.
            return

async def trend_alert(username: str = "admin", chat_id: Optional[int] = None, trigger: str = "auto") -> None:
    # 1. Load Config
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        
        # Default fallback
        if hasattr(user_settings.bot.proactive, "trend_alert"):
            conf = user_settings.bot.proactive.trend_alert
        else:
             from app.models.settings import TrendAlertConfig
             conf = TrendAlertConfig()
             
        global_settings = get_settings()
        ns_url = user_settings.nightscout.url or global_settings.nightscout.base_url
        ns_token = user_settings.nightscout.token or global_settings.nightscout.token
    except Exception as e:
        health.record_event("trend_alert", False, f"config_error: {e}")
        return

    if not conf.enabled and trigger == "auto":
        return

    # Resolve Chat ID
    chat_id = chat_id or await _get_chat_id()
    if not chat_id:
        return

    # 2. Fetch Data (Nightscout)
    from app.services.nightscout_client import NightscoutClient
    
    if not ns_url:
        health.record_event("trend_alert", False, "missing_ns_config")
        return

    client = NightscoutClient(str(ns_url), ns_token)
    entries = []
    try:
        now_utc = datetime.now(timezone.utc)
        # Fetch window + buffer
        start_dt = now_utc - timedelta(minutes=conf.window_minutes + 10)
        entries = await client.get_sgv_range(start_dt, now_utc, count=24)
    except Exception as e:
        health.record_event("trend_alert", False, f"ns_error: {e}")
        try: await client.aclose()
        except: pass
        return
    finally:
         try: await client.aclose()
         except: pass

    # 3. Analyze Trend (Slope/Delta)
    if not entries or len(entries) < conf.sample_points_min:
         health.record_event("trend_alert", False, f"heuristic_insufficient_data(points={len(entries)}, min={conf.sample_points_min})")
         return

    # Sort Chronological
    entries_sorted = sorted(entries, key=lambda x: x.date)
    
    # We focus on the window range exactly?
    # Or just last - first of the fetched batch?
    # Let's take the subset within window_minutes
    window_start_ms = (now_utc - timedelta(minutes=conf.window_minutes)).timestamp() * 1000
    window_entries = [e for e in entries_sorted if e.date >= window_start_ms]
    
    if len(window_entries) < 2:
        health.record_event("trend_alert", False, "heuristic_insufficient_data_window")
        return
        
    bg_first = window_entries[0].sgv
    bg_last = window_entries[-1].sgv
    if bg_first is None or bg_last is None: return
    
    delta_total = bg_last - bg_first
    
    # Calculate real duration in minutes
    t_first = window_entries[0].date / 1000.0
    t_last = window_entries[-1].date / 1000.0
    duration_min = (t_last - t_first) / 60.0
    
    if duration_min < 5: 
        return # Too short
        
    slope = delta_total / duration_min
    
    direction = "stable"
    if slope >= conf.rise_mgdl_per_min and delta_total >= conf.min_delta_total_mgdl:
        direction = "rise"
    elif slope <= conf.drop_mgdl_per_min and delta_total <= -conf.min_delta_total_mgdl:
        direction = "drop"
        
    if direction == "stable":
        health.record_event("trend_alert", False, f"heuristic_below_threshold(slope={slope:.2f}, delta_total={delta_total})")
        return

    # 4. Gating: Check Recent Treatments (Carbs/Bolus) from DB
    from app.core.db import get_engine, AsyncSession
    from app.models.treatment import Treatment
    from sqlalchemy import select
    
    engine = get_engine()
    has_recent_carbs = False
    has_recent_bolus = False
    
    search_window = max(conf.recent_carbs_minutes, conf.recent_bolus_minutes)
    cutoff = now_utc - timedelta(minutes=search_window)
    
    if engine:
        try:
            async with AsyncSession(engine) as session:
                # Optimized query? Or just fetch recent.
                stmt = (
                    select(Treatment)
                    .where(Treatment.user_id == username) # or check all?
                    .where(Treatment.created_at >= cutoff.replace(tzinfo=None)) 
                    # Note: treatment created_at usually naive UTC in DB, careful with TZ.
                    # Best practice: ensure model stores UTC.
                )
                res = await session.execute(stmt)
                rows = res.scalars().all()
                
                for r in rows:
                    # Parse time safely
                    c_time = r.created_at
                    if c_time.tzinfo is None: c_time = c_time.replace(tzinfo=timezone.utc)
                    
                    diff_min = (now_utc - c_time).total_seconds() / 60.0
                    
                    if r.carbs and r.carbs > 0 and diff_min <= conf.recent_carbs_minutes:
                         has_recent_carbs = True
                    
                    if r.insulin and r.insulin > 0 and diff_min <= conf.recent_bolus_minutes:
                         has_recent_bolus = True
        except Exception as e:
            logger.error(f"Trend DB check failed: {e}")
            pass

    if has_recent_carbs:
        health.record_event("trend_alert", False, f"heuristic_recent_carbs(minutes={conf.recent_carbs_minutes})")
        return
        
    if has_recent_bolus:
        health.record_event("trend_alert", False, f"heuristic_recent_bolus(minutes={conf.recent_bolus_minutes})")
        return

    # 5. Success -> Delegate to Router
    payload = {
        "current_bg": bg_last,
        "delta_total": int(delta_total),
        "slope": round(slope, 2),
        "direction": direction,
        "window_minutes": int(duration_min),
        "delta_arrow": f"{int(delta_total):+}"
    }

    from app.bot.llm import router
    reply = await router.handle_event(
        username=username,
        chat_id=chat_id,
        event_type="trend_alert",
        payload=payload
    )
    
    if reply and reply.text:
        await _send(
            None,
            chat_id,
            reply.text,
            log_context="proactive_trend",
        )
        # Mark sent in rules
        from app.bot.proactive_rules import mark_event_sent
        mark_event_sent("trend_alert")


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

    if not user_settings.bot.enabled:
        return

    # Resolve Chat ID early so inner functions can access it
    final_chat_id = chat_id or await _get_chat_id()
    if not final_chat_id:
        return

    # Helper to route safely at exit
    from app.bot.llm import router
    
    async def _route(payload_inner: dict):
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

    # 5. Find Candidate (Strict Combo Gating)
    treatments.sort(key=lambda x: x.created_at, reverse=True)
    candidate = None
    
    def is_combo_bolus(t) -> bool:
        # Must be a bolus with insulin
        if not (t.insulin and t.insulin > 0) and t.eventType not in ("Meal Bolus", "Correction Bolus", "Bolus"):
            return False
            
        # Check notes for markers
        notes = (t.notes or "").lower()
        markers = ["#dual", "#combo", "#extendido", "bolo_dual", "combo_followup"]
        if any(m in notes for m in markers):
            return True

        # Check for 'split:' syntax (App Sync)
        import re
        if "split:" in notes:
             # Basic check usually enough, but let's verify regex
             split_pattern = r"split:\s*([0-9]+(?:\.[0-9]+)?)\s*now\s*\+\s*([0-9]+(?:\.[0-9]+)?)\s*delayed\s*([0-9]+)m"
             if re.search(split_pattern, notes):
                 return True

        return False

    for t in treatments:
        if is_combo_bolus(t):
            candidate = t
            break
            
    if not candidate:
        # Check if we have ANY bolus, just to distinguish "no bolus" vs "no combo bolus"
        # Optional refinement, but user asked for "heuristic_not_combo_bolus"
        # If there are boluses but none are combo, use that reason.
        recent_bolus = next((t for t in treatments if (t.insulin and t.insulin > 0)), None)
        if recent_bolus:
             await _route({"reason_hint": "heuristic_not_combo_bolus"})
        else:
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
    # Fetch Context for Intelligent Decision (Rising vs Dropping)
    status_res = await tools.execute_tool("get_status_context", {})
    
    # Payload
    payload = {
        "treatment_id": tid,
        "bolus_units": candidate.insulin,
        "bolus_at": ts.isoformat(),
        "minutes_since": int(diff_min),
        "delay_minutes": conf.delay_minutes,
        "bg": getattr(status_res, "bg_mgdl", None),
        "trend": getattr(status_res, "direction", "Flat"),
        "delta": getattr(status_res, "delta_mgdl", 0)
    }
    
    await _route(payload)


async def morning_summary(username: str = "admin", chat_id: Optional[int] = None, trigger: str = "manual", mode: str = "full") -> None:
    """
    On-demand morning summary.
    Modes:
    - full: Always sends summary (Stats + Alerts).
    - alerts: Sends ONLY if there are notable events (hypo/hyper), else short/silent.
    """
    # Resolve default user
    if username == "admin":
        from app.core import config
        username = config.get_bot_default_username()

async def morning_summary(username: str = "admin", chat_id: Optional[int] = None, trigger: str = "manual", mode: str = "full") -> None:
    # 0. Cooldown (Anti-spam for manual commands)
    # We want to allow retrying quickly if needed, but maybe 2 min cooldown to prevent accidental double taps?
    # Let's use a short cooldown key "cmd:morning".
    if not cooldowns.is_ready("cmd:morning", 60): # 1 minute spam protection
         health.record_event("morning_summary", False, "silenced_recent(morning_summary)")
         return

    # 1. Resolve Chat ID
    if chat_id is None:
        chat_id = await _get_chat_id()
    if not chat_id:
        return

    # 2. Configuration & Defaults
    conf_hypo_mgdl = 70
    conf_hyper_mgdl = 250
    conf_hyper_min = 20
    range_hours = 8 # Configurable, but 8 is standard "night"
    
    # 3. Fetch Data (Nightscout)
    from app.services.nightscout_client import NightscoutClient
    
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        global_settings = get_settings()
        ns_url = user_settings.nightscout.url or global_settings.nightscout.base_url
        ns_token = user_settings.nightscout.token or global_settings.nightscout.token
    except Exception:
        ns_url = None
        ns_token = None

    if not ns_url:
        await _send(None, chat_id, "⚠️ Falta configuración de Nightscout.")
        return

    client = NightscoutClient(str(ns_url), ns_token)
    entries = []
    try:
        now_utc = datetime.now(timezone.utc)
        start_dt = now_utc - timedelta(hours=range_hours)
        entries = await client.get_sgv_range(start_dt, now_utc, count=range_hours * 12 + 60)
    except Exception as e:
        logger.error(f"Morning Summary NS fetch failed: {e}")
        await _send(None, chat_id, "⚠️ Error obteniendo datos de Nightscout.")
        return
    finally:
        await client.aclose()

    if not entries:
        if mode == "full":
             await _send(None, chat_id, f"Sin datos en las últimas {range_hours}h.")
        health.record_event("morning_summary", False, "no_data")
        return

    # 4. Analyze Data
    # Sort Chronological
    entries_sorted = sorted(entries, key=lambda x: x.date) 
    values_chrono = [e.sgv for e in entries_sorted if e.sgv is not None]
    dates_chrono = [e.date for e in entries_sorted if e.sgv is not None]

    if not values_chrono:
         health.record_event("morning_summary", False, "empty_values")
         return

    min_bg = min(values_chrono)
    max_bg = max(values_chrono)
    last_bg = values_chrono[-1]
    
    # Event Detection
    hypo_events = 0

async def post_meal_feedback(username: str = "admin", chat_id: Optional[int] = None) -> None:
    """
    Check for meals ~3h ago and ask for feedback to learn outcomes.
    """
    # 0. Config
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        if not user_settings.bot.enabled: return
    except Exception: return

    final_chat_id = chat_id or await _get_chat_id()
    if not final_chat_id: return

    # 1. Fetch Treatments (Last 4h)
    global_settings = get_settings()
    store = DataStore(Path(global_settings.data.data_dir))
    
    # We need NS or DB treatments. Let's use NightscoutClient as primary source for recent history
    ns_url = user_settings.nightscout.url or global_settings.nightscout.base_url
    if not ns_url: return

    client = NightscoutClient(str(ns_url), user_settings.nightscout.token)
    treatments = []
    try:
        treatments = await client.get_recent_treatments(hours=4)
        treatments.sort(key=lambda x: x.created_at, reverse=True)
    except: pass
    finally: await client.aclose()

    # 2. Find Candidates (Meals > 3h ago but < 3.5h ago)
    # We want to catch them "once" around the 3h mark.
    now = datetime.now(timezone.utc)
    
    candidate = None
    for t in treatments:
        # Check if it's a meal (has carbs or insulin)
        if (t.carbs and t.carbs > 30) or (t.insulin and t.insulin > 3):
             # Check Time
             ts = t.created_at
             if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
             diff_min = (now - ts).total_seconds() / 60.0
             
             # Target window: 180 min to 210 min (3h - 3.5h)
             if 180 <= diff_min <= 210:
                 candidate = t
                 break
    
    if not candidate: return

    # 3. Persistence Check
    events = store.load_events()
    tid = candidate.id or f"local_{candidate.created_at.timestamp()}"
    
    # Check if already asked
    prev = next((e for e in events if e.get("type") == "post_meal_feedback" and e.get("treatment_id") == tid), None)
    if prev: return

    # 4. Trigger
    from app.bot.llm import router
    
    payload = {
        "treatment_id": tid,
        "carbs": candidate.carbs,
        "insulin": candidate.insulin,
        "ago_min": int((now - candidate.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 60)
    }
    
    # Let router build message
    # Or build manually here for control? Router is safer for "personality".
    # But usually Router doesn't handle "post_meal_feedback" event type yet?
    # We can add it or just send direct message. 
    # Let's send direct message with buttons to ensure specific callback formats.
    
    text = (
        f"📊 **Check de Aprendizaje**\n"
        f"Hace 3h pusiste {candidate.insulin}U para {candidate.carbs}g.\n"
        f"¿Cómo resultó?"
    )
    
    buttons = [
        [InlineKeyboardButton("✅ Perfecta", callback_data=f"feedback_ok|{tid}")],
        [InlineKeyboardButton("📉 Me pasé (Hipo)", callback_data=f"feedback_low|{tid}")],
        [InlineKeyboardButton("📈 Me quedé corto (Hiper)", callback_data=f"feedback_high|{tid}")]
    ]
    
    from app.bot.service import bot_send
    await bot_send(
        chat_id=final_chat_id,
        text=text,
        bot=None,
        log_context="post_meal_feedback",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    
    # Mark done
    events.append({
        "type": "post_meal_feedback",
        "treatment_id": tid,
        "status": "asked",
        "timestamp": now.isoformat()
    })
    store.save_events(events)
    hyper_events = 0
    
    # Counters
    cons_low = 0
    cons_high = 0
    min_readings_low = 2 
    min_readings_high = max(1, int(conf_hyper_min / 5)) 
    
    highlight_events = [] 
    
    in_hypo = False
    in_hyper = False
    
    import zoneinfo
    try:
        tz_local = zoneinfo.ZoneInfo("Europe/Madrid")
    except Exception:
        tz_local = timezone.utc
    
    for i, v in enumerate(values_chrono):
        ts_ms = dates_chrono[i]
        dt = datetime.fromtimestamp(ts_ms / 1000, timezone.utc).astimezone(tz_local)
        time_str = dt.strftime("%H:%M")

        # Hypo check
        if v < conf_hypo_mgdl:
             cons_low += 1
             if cons_low == min_readings_low and not in_hypo:
                 hypo_events += 1
                 in_hypo = True
                 highlight_events.append(f"📉 Hipo detectada ({v} mg/dL) a las {time_str}")
        else:
             cons_low = 0
             in_hypo = False

        # Hyper check
        if v > conf_hyper_mgdl:
             cons_high += 1
             if cons_high == min_readings_high and not in_hyper:
                 hyper_events += 1
                 in_hyper = True
                 highlight_events.append(f"📈 Hiper persistente (> {conf_hyper_mgdl}) a las {time_str}")
        else:
             cons_high = 0
             in_hyper = False

    has_notable = (hypo_events > 0 or hyper_events > 0)

    # 5. Direct Response for "alerts" mode without events
    if mode == "alerts" and not has_notable:
        health.record_event("morning_summary", True, "sent_no_events")
        # Direct send for better UX than silence
        await _send(None, chat_id, f"🌙 Noche tranquila. Sin eventos destacables.")
        cooldowns.touch("cmd:morning")
        return

    # 6. Payload Construction
    payload = {
        "mode": mode,
        "bg": last_bg,
        "min_bg": min_bg,
        "max_bg": max_bg,
        "hypo_count": hypo_events,
        "hyper_count": hyper_events,
        "highlights": highlight_events,
        "range_hours": range_hours
    }

    # 7. Delegate to Router
    from app.bot.llm import router
    
    reply = await router.handle_event(
        username=username,
        chat_id=chat_id,
        event_type="morning_summary",
        payload=payload
    )
    
    if reply and reply.text:
        await _send(None, chat_id, reply.text, log_context="proactive_morning")
        # Mark usage
        cooldowns.touch("cmd:morning")
        
        # Log health (Success)
        reason = f"sent_morning_{mode}"
        if mode == "alerts": 
            reason += f"(hypo={hypo_events}, hyper={hyper_events})"
        health.record_event("morning_summary", True, reason)


async def light_guardian(username: str = "admin", chat_id: Optional[int] = None) -> None:
    """
    Wrapper around existing glucose monitor job using same bot instance.
    """
    try:
        from app.bot.service import run_glucose_monitor_job
        await run_glucose_monitor_job()
    except Exception as exc:
        logger.warning("Guardian job failed: %s", exc)

async def trend_alert(username: str = "admin", chat_id: Optional[int] = None, trigger: str = "auto") -> None:
    # 1. Load User Config & Defaults
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        
        # Load trend config (or default if missing)
        if hasattr(user_settings.bot.proactive, "trend_alert"):
            conf = user_settings.bot.proactive.trend_alert
        else:
             from app.models.settings import TrendAlertConfig
             conf = TrendAlertConfig()
             
        global_settings = get_settings()
        ns_url = user_settings.nightscout.url or global_settings.nightscout.base_url
        ns_token = user_settings.nightscout.token or global_settings.nightscout.token
    except Exception as e:
        logger.error(f"TrendAlert config load failed: {e}")
        health.record_event("trend_alert", False, f"config_error: {e}")
        return

    # Check Enabled
    if not user_settings.bot.enabled:
        return

    if not conf.enabled and trigger == "auto":
        return

    # Resolve Chat ID
    if chat_id is None:
        chat_id = await _get_chat_id()
    if not chat_id:
        return

    # 2. Fetch Data (Nightscout)
    from app.services.nightscout_client import NightscoutClient
    
    if not ns_url:
        health.record_event("trend_alert", False, "missing_ns_config")
        return

    client = NightscoutClient(str(ns_url), ns_token)
    entries = []
    try:
        now_utc = datetime.now(timezone.utc)
        start_dt = now_utc - timedelta(minutes=conf.window_minutes)
        # Fetch slightly more to be safe
        entries = await client.get_sgv_range(start_dt, now_utc, count=20)
    except Exception as e:
        logger.error(f"TrendAlert NS fetch failed: {e}")
        health.record_event("trend_alert", False, f"ns_error: {e}")
        try: await client.aclose()
        except: pass
        return
    finally:
         try: await client.aclose()
         except: pass

    # 3. Analyze Trend
    if not entries or len(entries) < conf.sample_points_min:
         health.record_event("trend_alert", False, f"heuristic_insufficient_data(points={len(entries)}, min={conf.sample_points_min})")
         return

    # Sort ASC
    entries_sorted = sorted(entries, key=lambda x: x.date)
    values = [e.sgv for e in entries_sorted if e.sgv is not None]
    if not values: return
    
    bg_first = values[0]
    bg_last = values[-1]
    
    first_date = entries_sorted[0].date / 1000.0
    last_date = entries_sorted[-1].date / 1000.0
    minutes_diff = (last_date - first_date) / 60.0
    
    if minutes_diff < 5: # Too short duration
         return

    slope = (bg_last - bg_first) / minutes_diff
    delta_total = bg_last - bg_first
    
    direction = "stable"
    is_alert = False
    
    # Check Conditions
    if slope >= conf.rise_mgdl_per_min and delta_total >= conf.min_delta_total_mgdl:
        direction = "rise"
        is_alert = True
    elif slope <= conf.drop_mgdl_per_min and delta_total <= -conf.min_delta_total_mgdl:
        direction = "drop"
        is_alert = True
        
    if not is_alert:
        health.record_event("trend_alert", False, f"heuristic_below_threshold(slope={slope:.2f}, delta={delta_total})")
        return

    # 4. Gating: Check Recent Treatments (Carbs/Bolus) from DB
    from app.core.db import get_engine, AsyncSession
    
    engine = get_engine()
    has_recent_carbs = False
    has_recent_bolus = False
    
    # We check treatments in MAX(recent_carbs, recent_bolus) window
    search_window = max(conf.recent_carbs_minutes, conf.recent_bolus_minutes)
    cutoff = now_utc - timedelta(minutes=search_window)
    
    from app.models.treatment import Treatment
    from sqlalchemy import select
    
    if engine:
        try:
            async with AsyncSession(engine) as session:
                stmt = (
                    select(Treatment)
                    .where(Treatment.user_id == username)
                    .where(Treatment.created_at >= cutoff.replace(tzinfo=None))
                    .order_by(Treatment.created_at.desc())
                )
                res = await session.execute(stmt)
                rows = res.scalars().all()
                
                # Check Carbs
                for r in rows:
                    c_time = r.created_at
                    if c_time.tzinfo is None: c_time = c_time.replace(tzinfo=timezone.utc)
                    c_mins = (now_utc - c_time).total_seconds() / 60.0
                    
                    if r.carbs and r.carbs > 0 and c_mins <= conf.recent_carbs_minutes:
                         has_recent_carbs = True
                    
                    if r.insulin and r.insulin > 0 and c_mins <= conf.recent_bolus_minutes:
                         has_recent_bolus = True
        except Exception as e:
            logger.error(f"Trend check DB error: {e}")
            pass

    # Evaluate Heuristics
    if has_recent_carbs:
         health.record_event("trend_alert", False, f"heuristic_recent_carbs(minutes={conf.recent_carbs_minutes})")
         return
         
    if has_recent_bolus:
         health.record_event("trend_alert", False, f"heuristic_recent_bolus(minutes={conf.recent_bolus_minutes})")
         return

    # 5. Dispatch
    payload = {
        "trigger": trigger,
        "current_bg": bg_last,
        "slope": round(slope, 2),
        "delta_total": delta_total,
        "window_minutes": int(minutes_diff),
        "direction": direction,
        "points_used": len(values)
    }
    
    # CASE 7: Micro-Bolus Assistance (Experimental)
    # Detect slow persistent rise and suggest small bump
    if direction == "rise" and bg_last > 140:
        try:
             # Fetch ISF/CF
            cf = 30.0 # Default
            if user_settings.cf:
                # Use lunch or average?
                cf = getattr(user_settings.cf, "lunch", 30.0)
            
            # Target
            target = 110.0
            if user_settings.targets: target = user_settings.targets.mid or 110.0
            
            # Calc needed
            diff = bg_last - target
            if diff > 0:
                needed = diff / cf
                # Safety: Suggest only 30-40% of full correction for a "nudge"
                safeguarded = needed * 0.4 
                
                # Round to 0.5 step (USER REQUEST)
                step = 0.5
                micro_u = round(safeguarded / step) * step
                
                # Minimum effective dose
                if micro_u >= 0.5:
                     # Cap at 1.0u for safety in proactive mode
                     if micro_u > 1.0: micro_u = 1.0
                     payload["suggested_micro_u"] = micro_u
        except Exception as e:
            logger.error(f"Microbolus calc error: {e}")

    from app.bot.llm import router
    await router.handle_event(username, chat_id, "trend_alert", payload)

async def check_isf_suggestions(username: str = "admin", chat_id: Optional[int] = None, trigger: str = "auto") -> None:
    # 0. Resolve User
    if username == "admin":
        from app.core import config
        username = config.get_bot_default_username()
    
    # 1. Config & Enabled Check
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        if not user_settings.bot.enabled: return
    except Exception: return
    
    chat_id = chat_id or await _get_chat_id()
    if not chat_id: return
    
    # 2. Prepare Analysis Service
    # We need NS Client and Profile from Settings
    from app.services.nightscout_client import NightscoutClient
    global_settings = get_settings()
    
    ns_url = user_settings.nightscout.url or global_settings.nightscout.base_url
    ns_token = user_settings.nightscout.token or global_settings.nightscout.token
    
    if not ns_url: return
    
    # Construct simplistic profile for analysis
    current_cf = {
        "breakfast": getattr(user_settings.cf, "breakfast", 30.0),
        "lunch": getattr(user_settings.cf, "lunch", 30.0),
        "dinner": getattr(user_settings.cf, "dinner", 30.0)
    }
    profile_settings = {
        "dia_hours": getattr(user_settings.iob, "dia_hours", 4.0),
        "curve": getattr(user_settings.iob, "curve", "bilinear"),
        "peak_minutes": getattr(user_settings.iob, "peak_minutes", 75)
    }

    client = NightscoutClient(str(ns_url), ns_token)
    service = IsfAnalysisService(client, current_cf, profile_settings)
    
    try:
        # Run 14 day analysis
        result: IsfAnalysisResponse = await service.run_analysis(username, days=14)
        
        # 3. Check for actionable items
        actionable = []
        for bucket in result.buckets:
            if bucket.status in ["strong_drop", "weak_drop"] and bucket.confidence == "high":
                actionable.append(bucket)
                
        if not actionable:
            if trigger == "manual":
                await _send(None, chat_id, "✅ Análisis completado. Sin cambios sugeridos.", log_context="isf_check_manual")
            return

        # 4. Check Persistence (Don't spam daily if already notified recently?)
        # For now, simplistic approach: Notify if found. User complained about NOT receiving.
        # But we should probably have a cooldown logic, e.g. once per week per item?
        # Let's rely on standard cooldown
        if not cooldowns.is_ready("isf_check", 3600 * 24 * 3): # 3 days cooldown
             if trigger == "manual": pass # force show
             else: return
        
        # 5. Send Notification
        msg = "📉 **Análisis de Sensibilidad (ISF)**\n\nHe detectado que tu configuración podría mejorarse:\n"
        for item in actionable:
            emoji = "🔴" if item.suggestion_type == "decrease" else "🔵"
            msg += f"\n{emoji} **{item.label}**: ISF {item.current_isf} ➔ **{item.suggested_isf}**\n"
            msg += f"   Razón: {item.status} ({int(item.change_ratio*100)}% cambio)\n"
            
        msg += "\nVe a **Ajustes > Análisis** para aplicar estos cambios."
        
        await _send(None, chat_id, msg, log_context="isf_check_notification")
        
    except Exception as e:
        logger.error(f"ISF Check failed: {e}")
        if trigger == "manual":
             await _send(None, chat_id, f"⚠️ Error analizando ISF: {e}", log_context="isf_check_error")
    finally:
        await client.aclose()
