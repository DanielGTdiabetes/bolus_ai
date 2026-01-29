from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from app.bot.state import cooldowns, health
from app.core import config
from app.core.settings import get_settings
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient, get_nightscout_client
from app.services.treatment_retrieval import get_recent_treatments_db
from app.services.iob import compute_iob_from_sources
from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2, GlucoseUsed
from app.services.basal_repo import get_latest_basal_dose
from app.services.nightscout_secrets_service import get_ns_config
from app.bot import tools, context_builder
from app.services.isf_analysis_service import IsfAnalysisService
from app.models.isf import IsfAnalysisResponse
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.autosens_service import AutosensService

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



# Diagnostic State (In-Memory)
_LAST_STATUS = {
    "basal": {"evaluated": False, "sent": False, "reason": "startup", "timestamp": None},
    "premeal": {"evaluated": False, "sent": False, "reason": "startup", "timestamp": None},
    "combo": {"evaluated": False, "sent": False, "reason": "startup", "timestamp": None},
    "trend": {"evaluated": False, "sent": False, "reason": "startup", "timestamp": None},
}

def record_proactive_status(module: str, sent: bool, reason: str, details: Optional[dict] = None):
    _LAST_STATUS[module] = {
        "evaluated": True,
        "sent": sent,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": details or {}
    }

def get_proactive_status():
    return _LAST_STATUS





async def basal_reminder(username: str = "admin", chat_id: Optional[int] = None, force: bool = False) -> None:
    # 0. Load Config
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        basal_conf = user_settings.bot.proactive.basal
        global_settings = get_settings()
    except Exception as e:
        record_proactive_status("basal", False, f"config_load_error: {e}")
        health.record_action("job:basal", False, error=f"config_load_error: {e}")
        return

    if not user_settings.bot.enabled:
        record_proactive_status("basal", False, "bot_disabled")
        return

    if not basal_conf.enabled:
        record_proactive_status("basal", False, "feature_disabled")
        return

    # 1. Resolve Chat ID
    final_chat_id = chat_id or basal_conf.chat_id or await _get_chat_id()
    if not final_chat_id:
        record_proactive_status("basal", False, "missing_chat_id")
        return

    # 2. Prepare Schedules
    schedules = basal_conf.schedule
    if not schedules and basal_conf.time_local:
        from app.models.settings import BasalScheduleItem
        legacy_item = BasalScheduleItem(
            id="legacy_default", 
            name="Basal", 
            time=basal_conf.time_local, 
            units=basal_conf.expected_units or 0.0
        )
        schedules = [legacy_item]
    
    if not schedules:
        record_proactive_status("basal", False, "missing_schedule")
        return

    # 3. Setup Context
    store = DataStore(Path(global_settings.data.data_dir))
    events = store.load_events()
    
    import zoneinfo
    tz = zoneinfo.ZoneInfo("Europe/Madrid")
    now_local = datetime.now(tz)
    today_str = now_local.strftime("%Y-%m-%d")

    # 3.5 Fetch Treatments
    recent_treatments = []
    try:
        recent_treatments = await get_recent_treatments_db(hours=24)
    except Exception as e:
        logger.warning(f"Failed to fetch treatments for basal check: {e}")

    # 4. Iterate Schedules
    for item in schedules:
        entry = next((e for e in events 
                      if e.get("type") == "basal_daily_status" 
                      and e.get("date") == today_str 
                      and e.get("schedule_id") == item.id), None)
        
        # Legacy fallback
        if not entry and item.id == "legacy_default":
             entry = next((e for e in events 
                      if e.get("type") == "basal_daily_status" 
                      and e.get("date") == today_str 
                      and not e.get("schedule_id")), None)
        
        # 4b. Smart Detection
        if not entry or entry.get("status") not in ("done", "dismissed", "done_detected", "snoozed"):
             target_h, target_m = map(int, item.time.split(":"))
             target_minutes = target_h * 60 + target_m
             
             # Reuseable verification logic
             def check_treatment_match(t_obj):
                 notes_t = (t_obj.notes or "").lower()
                 type_t = (t_obj.eventType or "").lower()
                 keywords = ["basal", "larga", "lenta"]
                 if item.name and item.name.lower() not in ["basal", "default"]:
                     keywords.append(item.name.lower())
                 
                 is_cand = any(k in notes_t for k in keywords) or "basal" in type_t
                 if not is_cand: return False
                 
                 # Time Check
                 if len(schedules) > 1:
                     if not t_obj.created_at: return False
                     # Ensure awareness
                     t_dt = t_obj.created_at
                     if t_dt.tzinfo is None:
                         t_dt = t_dt.replace(tzinfo=timezone.utc)
                     
                     t_local = t_dt.astimezone(tz)
                     t_min = t_local.hour * 60 + t_local.minute
                     diff = abs(t_min - target_minutes)
                     if diff > 180: return False # 3 hours
                 
                 return True

             found_match_t = None
             match_source = "external"
             
             # 1. Check DB Treatments (Nightscout Shadow)
             for t in recent_treatments:
                 if check_treatment_match(t):
                     found_match_t = t
                     match_source = f"treatments:{t.id}"
                     logger.info(f"Basal '{item.name}' detected in DB (id={t.id}).")
                     break
            
             # 2. Check Specific Basal Dose Table (App Manual Entry)
             if not found_match_t:
                 try:
                     # Check basal_dose table for entry today
                     latest_dose = await get_latest_basal_dose(username)
                     if latest_dose:
                        # Check date
                        eff_from = latest_dose.get("effective_from") # date object
                        created = latest_dose.get("created_at") # datetime
                        
                        is_today = False
                        if eff_from and str(eff_from) == today_str:
                            is_today = True
                        elif created:
                             if created.tzinfo is None:
                                 created = created.replace(tzinfo=timezone.utc)
                             c_local = created.astimezone(tz)
                             if c_local.strftime("%Y-%m-%d") == today_str:
                                 is_today = True
                        
                        if is_today:
                             # We assume only 1 basal per day usually, or latest is sufficient.
                             # If multiple schedules, we might need more granular checks but
                             # basal_dose table structure seems to handle 'dose_u' and 'effective_from'.
                             # It doesn't seem to have 'schedule_name' to distinguish Levemir/Lantus distinct shots?
                             # But usually basal is once a day. If found, we mark as done.
                             found_match_t = latest_dose
                             match_source = f"basal_dose:{latest_dose.get('id')}"
                             logger.info(f"Basal detected in `basal_dose` table (id={latest_dose.get('id')})")
                             
                 except Exception as exc:
                     logger.warning(f"Basal repo check failed: {exc}")

             # 3. Apply Match
             if found_match_t:
                 if not entry:
                     events.append({
                        "type": "basal_daily_status",
                        "date": today_str,
                        "schedule_id": item.id,
                        "status": "done_detected",
                        "detected_from": match_source,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                     })
                     store.save_events(events)
                     entry = events[-1]
                 else:
                     evt_idx = events.index(entry)
                     events[evt_idx]["status"] = "done_detected"
                     events[evt_idx]["detected_from"] = match_source
                     store.save_events(events)

        if entry:
            st = entry.get("status")
            if st in ("done", "dismissed", "done_detected"):
                 record_proactive_status("basal", False, f"already_{st}")
                 continue 
            elif st == "snoozed":
                 until_str = entry.get("snooze_until")
                 if until_str:
                     try:
                         until_dt = datetime.fromisoformat(until_str)
                         if datetime.now(timezone.utc) < until_dt:
                             record_proactive_status("basal", False, "snoozed")
                             continue 
                     except: pass
        
        # 5. Check Timing / Status Mapping
        try:
            target_h, target_m = map(int, item.time.split(":"))
            target_dt = now_local.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            
            diff_min = (now_local - target_dt).total_seconds() / 60.0
            
            basal_status_code = "not_due_yet"
            if diff_min < -30:
                basal_status_code = "not_due_yet"
            elif -30 <= diff_min <= 30:
                basal_status_code = "due_soon"
            elif diff_min > 30:
                basal_status_code = "late"
            
            # Skip if too early (unless force)
            if not force and basal_status_code == "not_due_yet":
                record_proactive_status("basal", False, "not_due_yet", {"diff_min": int(diff_min)})
                continue
                
        except ValueError:
            continue

        # 6. Execute Trigger
        suggested_units = item.units
        latest_dose_ctx = None

        if suggested_units <= 0.01:
             try:
                 found_latest = await get_latest_basal_dose(username)
                 if found_latest and found_latest.get("dose_u"):
                     suggested_units = float(found_latest.get("dose_u"))
                     latest_dose_ctx = found_latest
             except Exception as e:
                 logger.warning(f"Failed to fetch latest basal for suggestion: {e}")

        payload = {
            "persistence_status": entry.get("status") if entry else None,
            "today_str": today_str,
            "schedule_id": item.id,
            "schedule_name": item.name,
            "scheduled_time": item.time,
            "expected_units": suggested_units,
            "last_dose": latest_dose_ctx,
            "hours_late": max(0, diff_min / 60.0),
            # CRITICAL FIX: Explicit status object for Router
            "basal_status": {
                "status": basal_status_code,
                "diff_min": int(diff_min)
            }
        }
        
        from app.bot.llm import router
        reply = await router.handle_event(
            username=username,
            chat_id=final_chat_id,
            event_type="basal", 
            payload=payload
        )
        
        if reply and reply.text:
            from app.bot.service import bot_send
            await bot_send(
                chat_id=final_chat_id, 
                text=reply.text, 
                bot=None,
                log_context=f"proactive_basal_{item.id}",
                reply_markup=InlineKeyboardMarkup(reply.buttons) if reply.buttons else None
            )
            
            # Finalize
            health.record_event("basal", True, "sent")
            record_proactive_status("basal", True, "sent", {"status": basal_status_code})
            
            # We don't mark 'basal' generic sent in rules because this is schedule-specific?
            # Actually we probably should to avoid spam if multiple schedules overlap?
            # But here we return after ONE send.
            
            if not entry:
                events.append({
                    "type": "basal_daily_status",
                    "date": today_str,
                    "schedule_id": item.id,
                    "status": "asked",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                store.save_events(events)
            
            return
        else:
            # Router logic decided to skip (e.g. cooldown or other checks in handle_event)
            # Usually router returns None if it skips.
            # We assume router logged the reason in its own record_event call, 
            # but we can update our last status if we know it wasn't sent.
            # record_proactive_status("basal", False, "router_skipped") # Optional
            pass
    return

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

    # 3.5 Fetch Treatments from DB (Preferred over NS)
    recent_treatments = []
    try:
        # We fetch 24h to be safe
        recent_treatments = await get_recent_treatments_db(hours=24)
    except Exception as e:
        logger.warning(f"Failed to fetch treatments for basal check: {e}")

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
        
        # 4b. Smart Detection Logic (If not already handled)
        if not entry or entry.get("status") not in ("done", "dismissed", "done_detected", "snoozed"):
             # Look for matching treatment in recent history
             # Heuristic: Treatment with 'basal' in note OR insulin > 0 with 'basal' eventType?
             # Note: Nightscout often uses 'Correction Bolus' / 'Meal Bolus'. Basal is usually just a note or specific type 'Basal'/'Temp Basal'.
             # We look for keyword in notes.
             
             target_h, target_m = map(int, item.time.split(":"))
             target_minutes = target_h * 60 + target_m
             
             for t in recent_treatments:
                 notes = (t.notes or "").lower()
                 e_type = (t.eventType or "").lower()
                 
                 # Keywords: 'basal', or the specific name of the schedule item (e.g. 'lantus', 'tresiba')
                 keywords = ["basal", "larga", "lenta"]
                 if item.name and item.name.lower() not in ["basal", "default"]:
                     keywords.append(item.name.lower())
                     
                 is_basal_candidate = any(k in notes for k in keywords) or "basal" in e_type
                 
                 if is_basal_candidate:
                     # Check Time Proximity IF multiple schedules exist
                     # If only 1 schedule, any basal today counts? 
                     # Let's be safe: match within +/- 5 hours of target time?
                     # Or if 'schedules' has len > 1, be strict.
                     
                     match = True
                     if len(schedules) > 1:
                         # Strict time check
                         t_local = t.created_at.astimezone(tz)
                         t_minutes = t_local.hour * 60 + t_local.minute
                         diff = abs(t_minutes - target_minutes)
                         if diff > 180: # 3 hours
                             match = False
                             
                     if match:
                         # FOUND! It was already done.
                         logger.info(f"Basal '{item.name}' detected externally (id={t.id}). Suppressing reminder.")
                         if not entry:
                             events.append({
                                "type": "basal_daily_status",
                                "date": today_str,
                                "schedule_id": item.id,
                                "status": "done_detected",
                                "detected_from": t.id,
                                "updated_at": datetime.now(timezone.utc).isoformat()
                             })
                             store.save_events(events)
                             entry = events[-1] # Update reference
                         else:
                             # Update existing 'asked' or 'pending'
                             evt_idx = events.index(entry)
                             events[evt_idx]["status"] = "done_detected"
                             store.save_events(events)
                         break

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
        record_proactive_status("premeal", False, f"config_error: {e}")
        return

    # 2. Check Enabled (Config)
    if not premeal_conf.enabled and trigger == "auto":
        record_proactive_status("premeal", False, "disabled")
        return

    # 3. Resolve Chat ID (Config Priority)
    final_chat_id = chat_id or premeal_conf.chat_id or await _get_chat_id()
    if not final_chat_id:
        record_proactive_status("premeal", False, "missing_chat_id")
        return

    # 4. Check Cooldown (Dynamic from Config)
    # If TRIGGER is manual, bypass cooldown check in terms of "should I run?", but 
    # we might still want to record it.
    if trigger == "auto":
        silence_sec = premeal_conf.silence_minutes * 60
        if not cooldowns.is_ready("premeal", silence_sec):
            # calculate remaining just for diagnostics
            # we rely on cooldowns module but it doesn't return time left easily here
            # so we just record generic
            health.record_event("premeal", False, f"silenced_recent(premeal,{premeal_conf.silence_minutes}m)")
            record_proactive_status("premeal", False, "cooldown", {"limit_min": premeal_conf.silence_minutes})
            return
        
    # 5. Fetch Context (Tool)
    try:
        status_res = await tools.execute_tool("get_status_context", {"username": username})
        if isinstance(status_res, tools.ToolError):
            health.record_event("premeal", False, f"error_tool: {status_res.message}")
            record_proactive_status("premeal", False, f"tool_error: {status_res.message}")
            return  
    except Exception as e:
        logger.error(f"Premeal check failed: {e}")
        health.record_event("premeal", False, f"error_tool: {e}")
        record_proactive_status("premeal", False, f"tool_exception: {e}")
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
         health.record_event("premeal", False, "skipped_missing_bg")
         record_proactive_status("premeal", False, "missing_bg_data")
         return

    # 7. Heuristic (Configurable Thresholds)
    delta_val = delta if delta is not None else 0
    bg_val = float(bg)
    
    th_bg = premeal_conf.bg_threshold_mgdl
    th_delta = premeal_conf.delta_threshold_mgdl
    
    if bg_val < th_bg and trigger == "auto":
        record_proactive_status("premeal", False, "thresholds_not_met", {"bg": bg_val, "threshold": th_bg})
        health.record_event("premeal", False, f"heuristic_low_bg(bg={int(bg_val)}<th={th_bg})")
        return

    # Allow delta=0 if BG is very high? For now stick to config.
    if delta_val < th_delta and bg_val < 200 and trigger == "auto":
        # If BG is huge (200+), maybe we nudge even if stable?
        # Current logic: strict delta.
        record_proactive_status("premeal", False, "thresholds_not_met", {"delta": delta_val, "threshold": th_delta})
        health.record_event("premeal", False, f"heuristic_low_delta(delta={delta_val}<th={th_delta})")
        return
        
    payload = {"bg": bg_val, "trend": direction, "delta": delta_val, "trigger": trigger}

    # 8. Delegate to Router
    from app.bot.llm import router

    reply = await router.handle_event(
        username=username,
        chat_id=final_chat_id,
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
            final_chat_id,
            reply.text,
            log_context="proactive_premeal",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        # Mark sent
        from app.bot.proactive_rules import mark_event_sent
        mark_event_sent("premeal")
        health.record_event("premeal", True, "sent")
        record_proactive_status("premeal", True, "sent", {"bg": bg_val})
    else:
        # Router skipped (e.g. user intent check)
        record_proactive_status("premeal", False, "router_skipped")

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
        if not user_settings.bot.proactive.combo_followup:
             from app.models.settings import ComboFollowupConfig
             conf = ComboFollowupConfig()
        else:
             conf = user_settings.bot.proactive.combo_followup
             
        global_settings = get_settings()
        
    except Exception as e:
        logger.error(f"Combo config load failed: {e}")
        health.record_event("combo_followup", False, f"config_load_err: {e}")
        record_proactive_status("combo", False, f"config_error: {e}")
        return

    if not user_settings.bot.enabled:
        record_proactive_status("combo", False, "bot_disabled")
        return

    # Resolve Chat ID
    final_chat_id = chat_id or await _get_chat_id()
    if not final_chat_id:
        record_proactive_status("combo", False, "missing_chat_id")
        return

    # Helper
    from app.bot.llm import router
    
    async def _route(payload_inner: dict):
        cid = final_chat_id
        if not cid: return

        reply = await router.handle_event(
            username=username,
            chat_id=cid,
            event_type="combo_followup",
            payload=payload_inner
        )
        
        if reply and reply.text:
            events.append({
                 "type": "combo_followup_record",
                 "treatment_id": payload_inner.get("treatment_id"),
                 "status": "asked",
                 "asked_at": datetime.now(timezone.utc).isoformat()
            })
            store.save_events(events)
            
            from telegram import InlineKeyboardMarkup
            await _send(
                None, 
                cid,
                reply.text,
                log_context="proactive_combo",
                reply_markup=InlineKeyboardMarkup(reply.buttons) if reply.buttons else None,
            )
            record_proactive_status("combo", True, "sent")
        else:
            record_proactive_status("combo", False, "router_skipped")

    # 2. Config Check
    if not conf.enabled:
        record_proactive_status("combo", False, "disabled")
        await _route({"reason_hint": "heuristic_disabled"})
        return

    # 3. Check Silence (Rules)
    from app.bot.proactive_rules import check_silence
    
    if conf.quiet_hours_start and conf.quiet_hours_end:
        from app.bot.proactive_rules import _is_quiet_hours
        if _is_quiet_hours(conf.quiet_hours_start, conf.quiet_hours_end):
             record_proactive_status("combo", False, "quiet_hours")
             await _route({"reason_hint": "silenced_quiet_hours(combo_followup)"})
             return

    # 4. Fetch Treatments
    treatments = []
    try:
        treatments = await get_recent_treatments_db(hours=conf.window_hours)
    except Exception as e:
        logger.error(f"Combo check DB error: {e}")
        record_proactive_status("combo", False, f"db_error: {e}")
        return

    # 5. Find Candidate
    treatments.sort(key=lambda x: x.created_at, reverse=True)
    candidate = None
    
    def is_combo_bolus(t) -> bool:
        if not (t.insulin and t.insulin > 0) and t.eventType not in ("Meal Bolus", "Correction Bolus", "Bolus"):
            return False
            
        notes = (t.notes or "").lower()
        markers = ["#dual", "#combo", "#extendido", "bolo_dual", "combo_followup"]
        if any(m in notes for m in markers):
            return True

        import re
        if "split:" in notes:
             split_pattern = r"split:\s*([0-9]+(?:\.[0-9]+)?)\s*now\s*\+\s*([0-9]+(?:\.[0-9]+)?)\s*delayed\s*([0-9]+)m"
             if re.search(split_pattern, notes):
                 return True

        return False

    for t in treatments:
        if is_combo_bolus(t):
            candidate = t
            break
            
    if not candidate:
        recent_bolus = next((t for t in treatments if (t.insulin and t.insulin > 0)), None)
        reason = "heuristic_not_combo_bolus" if recent_bolus else "heuristic_no_candidate_bolus"
        record_proactive_status("combo", False, reason)
        await _route({"reason_hint": reason})
        return

    # 6. Check Persistence
    store = DataStore(Path(global_settings.data.data_dir))
    events = store.load_events()
    tid = candidate.id
    if not tid:
         record_proactive_status("combo", False, "missing_tid")
         await _route({"reason_hint": "heuristic_no_treatment_id"})
         return

    previous_record = next((e for e in reversed(events) if e.get("treatment_id") == tid and e.get("type") == "combo_followup_record"), None)
    
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
            record_proactive_status("combo", False, f"already_{status}")
            await _route({"reason_hint": "heuristic_already_followed_up"})
            return

    # 7. Check Time
    now_utc = datetime.now(timezone.utc)
    ts = candidate.created_at
    if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
    
    diff_min = (now_utc - ts).total_seconds() / 60
    
    if diff_min < conf.delay_minutes:
         record_proactive_status("combo", False, "too_soon", {"diff_min": int(diff_min), "target": conf.delay_minutes})
         await _route({
             "reason_hint": f"heuristic_too_soon(minutes_since={int(diff_min)}, delay={conf.delay_minutes})",
             "minutes_since": int(diff_min),
             "delay_minutes": conf.delay_minutes
         })
         return

    # 8. Success: Candidate Eligible
    status_res = await tools.execute_tool("get_status_context", {})
    
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

    # 4. Fetch Treatments (Local DB First)
    treatments = []
    try:
        treatments = await get_recent_treatments_db(hours=conf.window_hours)
    except Exception as e:
        logger.error(f"Combo check DB error: {e}")
        # Could fallback to NS here if critical, but DB is primary now
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

    # Search in reverse to find the latest status (handle snoozed correctly)
    previous_record = next((e for e in reversed(events) if e.get("treatment_id") == tid and e.get("type") == "combo_followup_record"), None)
    
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
    
    # 3. Fetch Data (Nightscout)
    client = None
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        client = get_nightscout_client(user_settings)
    except Exception as e:
        logger.error(f"Settings load error: {e}")
        
    if not client:
        await _send(None, chat_id, "⚠️ Falta configuración de Nightscout.")
        return
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
    # 1. Fetch Treatments (Last 4h from DB)
    global_settings = get_settings()
    store = DataStore(Path(global_settings.data.data_dir))
    
    treatments = await get_recent_treatments_db(hours=4)
    if not treatments: return
    treatments.sort(key=lambda x: x.created_at, reverse=True)

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
        
        if hasattr(user_settings.bot.proactive, "trend_alert"):
            conf = user_settings.bot.proactive.trend_alert
        else:
             from app.models.settings import TrendAlertConfig
             conf = TrendAlertConfig()
             
        global_settings = get_settings()
    except Exception as e:
        logger.error(f"TrendAlert config load failed: {e}")
        health.record_event("trend_alert", False, f"config_error: {e}")
        record_proactive_status("trend", False, f"config_error: {e}")
        return

    # Check Enabled
    if not user_settings.bot.enabled:
        record_proactive_status("trend", False, "bot_disabled")
        return

    if not conf.enabled and trigger == "auto":
        record_proactive_status("trend", False, "disabled")
        return

    # Resolve Chat ID
    if chat_id is None:
        chat_id = await _get_chat_id()
    if not chat_id:
        record_proactive_status("trend", False, "missing_chat_id")
        return

    # Check Cooldown (Early check to avoid DB/NS hits if not needed)
    # But for "Soft Mode" we need a different cooldown (6h) vs normal cooldown.
    # We'll check standard cooldown first.
    silence_sec = conf.silence_minutes * 60
    if trigger == "auto" and not cooldowns.is_ready("trend_alert", silence_sec):
         record_proactive_status("trend", False, "cooldown", {"limit_min": conf.silence_minutes})
         return

    # 2. Fetch Data (Nightscout)
    client = get_nightscout_client(user_settings)
    if not client:
        health.record_event("trend_alert", False, "missing_ns_config")
        record_proactive_status("trend", False, "missing_ns_config")
        return
        
    entries = []
    try:
        now_utc = datetime.now(timezone.utc)
        start_dt = now_utc - timedelta(minutes=conf.window_minutes)
        entries = await client.get_sgv_range(start_dt, now_utc, count=20)
    except Exception as e:
        logger.error(f"TrendAlert NS fetch failed: {e}")
        health.record_event("trend_alert", False, f"ns_error: {e}")
        record_proactive_status("trend", False, f"ns_error: {e}")
        try: await client.aclose()
        except: pass
        return
    finally:
         try: await client.aclose()
         except: pass

    # 3. Analyze Trend
    if not entries or len(entries) < conf.sample_points_min:
         record_proactive_status("trend", False, "insufficient_data", {"points": len(entries)})
         return

    entries_sorted = sorted(entries, key=lambda x: x.date)
    values = [e.sgv for e in entries_sorted if e.sgv is not None]
    if not values: return
    
    bg_first = values[0]
    bg_last = values[-1]
    
    first_date = entries_sorted[0].date / 1000.0
    last_date = entries_sorted[-1].date / 1000.0
    minutes_diff = (last_date - first_date) / 60.0
    
    if minutes_diff < 5: 
         record_proactive_status("trend", False, "duration_too_short")
         return

    slope = (bg_last - bg_first) / minutes_diff
    delta_total = bg_last - bg_first
    
    direction = "stable"
    is_alert = False
    
    # Check Conditions (Standard)
    if slope >= conf.rise_mgdl_per_min and delta_total >= conf.min_delta_total_mgdl:
        direction = "rise"
        is_alert = True
    elif slope <= conf.drop_mgdl_per_min and delta_total <= -conf.min_delta_total_mgdl:
        direction = "drop"
        is_alert = True
        
    # Soft Mode Logic
    soft_triggered = False
    if not is_alert and getattr(conf, "trend_soft_mode", True) and trigger == "auto":
        # Relaxed check: Accept if Slope is met, but delta is smaller?
        # Or if slope is slightly smaller (-1.2 instead of -1.5) but sustained?
        # User request: "si se cumple pendiente pero no min_delta_total".
        
        slope_met = False
        if slope >= conf.rise_mgdl_per_min: 
            direction = "rise"
            slope_met = True
        elif slope <= conf.drop_mgdl_per_min:
            direction = "drop"
            slope_met = True
            
        if slope_met:
             # Check separate 6h cooldown for soft alerts to prevent spam
             # We use a derived key "trend_soft"
             if cooldowns.is_ready("trend_soft", 6 * 60 * 60):
                 is_alert = True
                 soft_triggered = True
                 logger.info(f"Trend Soft Trigger: slope={slope} delta={delta_total}")

    if not is_alert:
        health.record_event("trend_alert", False, f"heuristic_below_threshold(slope={slope:.2f}, delta={delta_total})")
        record_proactive_status("trend", False, "thresholds_not_met", {"slope": slope, "delta": delta_total})
        return

    # 4. Gating: Check Recent Treatments
    from app.core.db import SessionLocal
    has_recent_carbs = False
    has_recent_bolus = False
    
    search_window = max(conf.recent_carbs_minutes, conf.recent_bolus_minutes)
    cutoff = now_utc - timedelta(minutes=search_window)
    
    from app.models.treatment import Treatment
    from sqlalchemy import select
    
    try:
        async with SessionLocal() as session:
            stmt = (
                select(Treatment)
                .where(Treatment.user_id == username)
                .where(Treatment.created_at >= cutoff.replace(tzinfo=None))
                .order_by(Treatment.created_at.desc())
            )
            res = await session.execute(stmt)
            rows = res.scalars().all()
            
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

    if has_recent_carbs:
         record_proactive_status("trend", False, "recent_carbs")
         health.record_event("trend_alert", False, f"heuristic_recent_carbs(minutes={conf.recent_carbs_minutes})")
         return
         
    if has_recent_bolus:
         record_proactive_status("trend", False, "recent_bolus")
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
    
    # Micro-bolus logic (preserved)
    if direction == "rise" and bg_last > 140:
        try:
            cf = 30.0
            if user_settings.cf: cf = getattr(user_settings.cf, "lunch", 30.0)
            target = 110.0
            if user_settings.targets: target = user_settings.targets.mid or 110.0
            diff = bg_last - target
            if diff > 0:
                needed = diff / cf
                safeguarded = needed * 0.4 
                step = 0.5
                micro_u = round(safeguarded / step) * step
                if micro_u >= 0.5:
                     if micro_u > 1.0: micro_u = 1.0
                     payload["suggested_micro_u"] = micro_u
        except Exception as e:
            logger.error(f"Microbolus calc error: {e}")

    from app.bot.llm import router
    await router.handle_event(username, chat_id, "trend_alert", payload)
    
    # Mark usage if sent (Router marks general sent, we mark specific or soft)
    if soft_triggered:
        cooldowns.touch("trend_soft") # Mark 6h cooldown
        health.record_event("trend_alert", True, "sent_soft_mode")
        record_proactive_status("trend", True, "sent_soft")
    else:
        # Standard cooldown handled by rules.mark_event_sent in router usually?
        # Router trend_alert handler calls health.record_event but NOT rules.mark_event_sent?
        # Checking router: yes it does record_event("trend_alert", True, reason).
        # But proactive_rules needs update?
        # Router lines 504 check rules.check_silence, but line 558 just records event.
        # We should ensure mark_event_sent is called.
        from app.bot import proactive_rules as rules
        rules.mark_event_sent("trend_alert")
        record_proactive_status("trend", True, "sent_standard")

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
    # 2. Fetch Data (Nightscout)
    client = get_nightscout_client(user_settings)
    
    if not client:
        health.record_event("trend_alert", False, "missing_ns_config")
        return
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
    from app.core.db import SessionLocal
    has_recent_carbs = False
    has_recent_bolus = False
    
    # We check treatments in MAX(recent_carbs, recent_bolus) window
    search_window = max(conf.recent_carbs_minutes, conf.recent_bolus_minutes)
    cutoff = now_utc - timedelta(minutes=search_window)
    
    from app.models.treatment import Treatment
    from sqlalchemy import select
    
    try:
        async with SessionLocal() as session:
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
    
    # 2. Run Generation (Unified Engine)
    from app.core.db import SessionLocal
    from app.services.suggestion_engine import generate_suggestions_service
    from app.models.suggestion import ParameterSuggestion
    from sqlalchemy import select
    
    created_count = 0
    
    try:
        async with SessionLocal() as session:
            # Run generation (includes ISF now)
            # Use 14 days for robust ISF
            stats = await generate_suggestions_service(username, 14, session, settings=user_settings)
            created_count = stats.get("created", 0)
            
            # 3. Notify NEW Pending Suggestions
            # We look for suggestions created in the last 5 minutes to notify
            cutoff = datetime.utcnow() - timedelta(minutes=5)
            stmt = select(ParameterSuggestion).where(
                ParameterSuggestion.user_id == username,
                ParameterSuggestion.status == "pending",
                ParameterSuggestion.created_at >= cutoff,
                ParameterSuggestion.parameter == "isf" # Focus on ISF as per job name, or all? Job name is isf_check.
            )
            res = await session.execute(stmt)
            new_items = res.scalars().all()
            
            if not new_items:
                if trigger == "manual":
                    await _send(None, chat_id, "✅ Análisis completado. Sin cambios sugeridos.", log_context="isf_check_manual")
                return

            for sug in new_items:
                # Format Notification
                item_label = sug.meal_slot
                suggested_val = sug.evidence.get("new_isf", "?")
                current_val = sug.evidence.get("old_isf", "?")
                confidence = sug.evidence.get("confidence", "medium")
                
                emoji = "🔴" if sug.direction == "decrease" else "🔵"
                msg = (
                    f"📉 **Sugerencia ISF: {item_label}**\n"
                    f"{emoji} {sug.reason}\n"
                    f"Actual: `{current_val}` -> Sugerido: **{suggested_val}**\n"
                    f"Confianza: {confidence}"
                )
                
                keyboard = [
                    [
                        InlineKeyboardButton(f"✅ Aceptar ({suggested_val})", 
                                           callback_data=f"autosens_confirm|{sug.id}|{suggested_val}|{sug.meal_slot}"),
                        InlineKeyboardButton("❌ Descartar", callback_data=f"autosens_cancel|{sug.id}")
                    ]
                ]
                
                await _send(
                    None, 
                    chat_id, 
                    msg, 
                    log_context="isf_check_notification",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
            # Update cooldown
            cooldowns.touch("isf_check")

    except Exception as e:
        logger.error(f"ISF Check failed: {e}")
        if trigger == "manual":
             await _send(None, chat_id, f"⚠️ Error analizando ISF: {e}", log_context="isf_check_error")



async def check_app_notifications(username: str = "admin", chat_id: Optional[int] = None, trigger: str = "auto") -> None:
    """
    Periodic job to check the centralized NotificationService for any 'unread' items 
    (Pending Suggestions, Evaluations Ready, Basal Reviews, etc.) and notify the user.
    """
    # 0. Resolve User
    if username == "admin":
        from app.core import config
        username = config.get_bot_default_username()

    # 1. Config Check
    try:
        user_settings = await context_builder.get_bot_user_settings_safe()
        if not user_settings.bot.enabled: return
        # Check global proactive switch if exists, or specific 'notifications' switch?
        # For now, if bot is enabled, we assume this helpful feature is enabled.
    except Exception: return

    chat_id = chat_id or await _get_chat_id()
    if not chat_id: return

    # 2. Check Cooldown (Don't nag too often for the SAME state)
    # We use a longer chill time (2 hours) to avoid spamming "You have unread items".
    # Unless trigger is manual.
    if trigger == "auto" and not cooldowns.is_ready("app_notif_check", 120 * 60): 
        return

    # 3. Query Notification Service
    from app.core.db import SessionLocal
    from app.services.notification_service import get_notification_summary_service
    
    summary = {}
    try:
        async with SessionLocal() as session:
            # We must use "admin" or correct user_id. 
            # Context builder resolved settings for 'username', let's use that.
            summary = await get_notification_summary_service(username, session)
    except Exception as e:
        logger.error(f"App Notification Check failed: {e}")
        return

    # 4. Process Unread
    if not summary.get("has_unread"):
        if trigger == "manual":
            await _send(None, chat_id, "✅ No tienes notificaciones pendientes.")
        return

    # Filter only unread items
    unread_items = [i for i in summary.get("items", []) if i.get("unread")]
    
    if not unread_items:
        return

    # 5. Build Message
    # We want a concise summary.
    # Title
    lines = ["🔔 **Avisos pendientes**"]
    
    for item in unread_items:
        # e.g. "Create 3 suggestions" -> "• Sugerencias pendientes (3)"
        title = item.get("title", "Aviso")
        count = item.get("count", 1)
        msg_body = item.get("message", "")
        
        icon = "🔹"
        if item.get("priority") == "high": icon = "🔸"
        if item.get("priority") == "critical": icon = "🔴"
        
        # Format: "🔸 Impacto disponible (2)"
        # Or detailed? Let's use Message provided by service roughly.
        lines.append(f"{icon} **{title}**")
        if count > 1:
            lines[-1] += f" ({count})"
        lines.append(f"_{msg_body}_") 
        lines.append("") # spacer

    lines.append("ℹ️ _Las notificaciones se gestionan desde la app._")

    app_url = config.get_public_app_url()
    if app_url:
        lines.append(f"[Abrir App]({app_url})")

    text_msg = "\n".join(lines)

    # 6. Send
    await _send(None, chat_id, text_msg, log_context="proactive_app_notifications")

    # 7. Update Cooldown
    # Only if auto.
    if trigger == "auto":
        cooldowns.touch("app_notif_check")


async def check_supplies_status(username: str = "admin", chat_id: Optional[int] = None) -> None:
    """
    Proactively checks for low stock of supplies and notifies the user.
    """
    # 0. Cooldown (Don't spam daily check)
    if not cooldowns.is_ready("supplies_check", 3600 * 24 * 0.9): # Once every ~21h
        return

    # 1. Resolve Chat ID
    if chat_id is None:
        chat_id = await _get_chat_id()
    if not chat_id:
        return

    # 2. Check Stock using Tool Logic
    try:
        from app.core.db import SessionLocal
        from app.models.user_data import SupplyItem
        from sqlalchemy import select
        
        warnings = []
        
        async with SessionLocal() as session:
             # simplistic resolution
             stmt = select(SupplyItem).where(SupplyItem.quantity >= 0) # get all
             result = await session.execute(stmt)
             items = result.scalars().all()
             
             for item in items:
                 # Check simple thresholds
                 msg = None
                 # Normalize key
                 key = (item.item_key or "").lower()
                 qty = item.quantity
                 
                 if "aguja" in key or "needle" in key:
                     if qty < 10: msg = f"⚠️ Quedan pocas agujas ({item.item_key}): {qty}"
                 elif "sensor" in key:
                     if qty < 3: msg = f"⚠️ Quedan pocos sensores ({item.item_key}): {qty}"
                 elif "reservori" in key or "reservoir" in key:
                     if qty < 3: msg = f"⚠️ Quedan pocos reservorios ({item.item_key}): {qty}"
                 
                 if msg:
                     warnings.append(msg)
                     
        if warnings:
            text = "📦 **Aviso de Suministros**\n\n" + "\n".join(warnings)
            await _send(
                None, 
                chat_id, 
                text, 
                log_context="proactive_supplies"
            )
            cooldowns.touch("supplies_check")
            
    except Exception as e:
        logger.error(f"Supplies check failed: {e}")


async def check_active_plans(username: str = "admin", chat_id: Optional[int] = None) -> None:
    """
    Checks for active bolus plans (Dual/Extended) that are due.
    Source: active_plans.json (Generic DataStore)
    """
    # 1. Resolve Chat ID
    final_chat_id = chat_id or await _get_chat_id()
    if not final_chat_id: return
    
    # 2. Load Plans
    global_settings = get_settings()
    store = DataStore(Path(global_settings.data.data_dir))
    
    try:
        data = store.load_json("active_plans.json")
        # Structure: { "plans": [...] }
        plans = data.get("plans", []) if data else []
    except Exception:
        return # File missing or corrupt
        
    if not plans: return
        
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    dirty = False
    
    from app.bot.service import bot_send
    
    active_plans_kept = []
    
    for p in plans:
        # Schema: { id, created_at_ts, upfront_u, later_u_planned, later_after_min, status, notes }
        if p.get("status") != "pending":
            continue
            
        created_at_ts = p.get("created_at_ts", 0)
        delay_min = p.get("later_after_min", 0)
        due_ts = created_at_ts + (delay_min * 60 * 1000)
        
        # Check if due (with 2 min buffer to allow processing)
        if now_ms >= due_ts:
            # IT IS TIME!
            later_u = p.get("later_u_planned", 0)
            notes = p.get("notes", "")
            
            # Send Notification
            text = (
                f"⏰ **Recordatorio de Bolo Dual**\n"
                f"Han pasado {delay_min} min.\n"
                f"Es hora de la segunda dosis: **{later_u} U**\n"
                f"_{notes}_"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton(f"✅ Poner {later_u} U", callback_data=f"accept_manual|{later_u}|{p.get('id')}"),
                    InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel|{p.get('id')}")
                ]
            ]
            
            try:
                await bot_send(
                    chat_id=final_chat_id,
                    text=text,
                    bot=None,
                    log_context="active_plan_reminder",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                # Mark as notified/completed to avoid loop
                dirty = True
                continue # Do not add to kept list (Remove it)
                
            except Exception as e:
                logger.error(f"Failed to send plan reminder: {e}")
                # Keep it to retry? Or fail safe?
                active_plans_kept.append(p)
        else:
            # Keep pending
            active_plans_kept.append(p)
            
    if dirty:
        store.save_json("active_plans.json", {"plans": active_plans_kept})
