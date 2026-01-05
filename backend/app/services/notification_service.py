
import logging
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, update

from app.models.notifications import UserNotificationState
from app.models.suggestion import ParameterSuggestion
from app.models.evaluation import SuggestionEvaluation
from app.services.basal_engine import get_advice_service

logger = logging.getLogger(__name__)

async def get_notification_summary_service(user_id: str, db: AsyncSession):
    # 1. Fetch Notification States
    stmt = select(UserNotificationState).where(UserNotificationState.user_id == user_id)
    states = (await db.execute(stmt)).scalars().all()
    state_map = {s.key: s.seen_at for s in states}
    
    items = []
    
    # --- Check 1: Pending Suggestions ---
    q_pend = select(ParameterSuggestion).where(
        ParameterSuggestion.user_id == user_id,
        ParameterSuggestion.status == 'pending'
    ).order_by(ParameterSuggestion.created_at.desc())
    pending = (await db.execute(q_pend)).scalars().all()
    
    count_pend = len(pending)
    if count_pend > 0:
        latest = pending[0].created_at
        # Assuming timestamps are timezone aware/naive consistency. 
        # Models usually use datetime.utcnow via default.
        # UserNotificationState also uses datetime.utcnow.
        
        # If user has 'seen' record, compare timestamps
        last_seen = state_map.get("suggestion_pending")
        
        is_unread = True
        if last_seen and last_seen >= latest:
            is_unread = False
            
        # Per prompt: show item if count > 0.
        # But 'has_unread' depends on seen state.
        # Wait, prompt says: "no visto" = evaluations creadas...
        # Prompt logic: unread = count > 0 AND (no existe key OR seen_at < max(created_at)).
        
        # If read, do we show it in the list? 
        # "listar items con ... badge count".
        # Yes, we list current status, red dot depends on unread.
        
        # Actually prompt says: "Tipos de avisos... suggestion_pending: Condicion: existen pending."
        # The unread flag drives the dot.
        
        if is_unread:
            items.append({
                "type": "suggestion_pending",
                "count": count_pend,
                "title": "Sugerencias pendientes",
                "message": f"Tienes {count_pend} sugerencias por revisar.",
                "route": "#/suggestions",
                "unread": True,
                "priority": "medium"
            })
        else:
            # Even if read, user implies we might list them? 'abrir panel ... listar items'.
            # PROMPT clarification: "Si no tienes seen... considera no visto".
            # "Items (solo estos 3)". If seen, does it disappear from list?
            # "Solo avisos accionables". If I already saw it, do I need to see it again in the list?
            # Probably yes, until action taken. But red dot goes away.
            # Let's include it with unread=False for UI logic?
            # Prompt example response shows items. It doesn't explicitly say hide if read.
            # BUT 'basal_review_today' says "Revisa ... y aun no se ha marcado visto".
            # This implies if seen, it disappears from list?
            # Let's assume list contains ACTIVE alerts. Unread status denotes NEW.
            # EXCEPT basal advice: if seen for today, maybe we hide it to reduce noise?
            # "Basal review today: Condicion ... y aun no se ha marcado visto".
            # This implies if seen, it is GONE from list.
            #
            # Let's apply "Hide if seen" for basal review.
            # For suggestions:Pending exists regardless of seen.
            # "suggestion_pending ... Condicion: existen parameter_suggestion".
            # It doesn't say "and not seen".
            # Red dot logic: "Punto rojo se enciende si hay >= 1 aviso no visto".
            # So list shows Pending Suggestions (even if seen), but red dot is off.

            items.append({
                "type": "suggestion_pending",
                "count": count_pend,
                "title": "Sugerencias pendientes",
                "message": f"Tienes {count_pend} sugerencias por revisar.",
                "route": "#/suggestions",
                "unread": False,
                "priority": "medium"
            })

    # --- Check 2: Evaluation Ready ---
    # Evaluations accepted but not seen/acknowledged.
    # Logic: "evaluaciones con created_at > last_seen(evaluation_ready)"
    # count = count(*) ...
    # This implies we count NEW ones.
    # If I see them, count goes to 0? Or just unread goes to false?
    # "Evaluation Ready ... Condicion: existen sugerencias accepted con evaluacion disponible y no marcada como seen".
    # This implies if marked seen, they drop from the "Evaluation Ready" condition.
    # So we prefer to filter by seen_at.
    
    last_seen_eval = state_map.get("evaluation_ready")
    
    q_eval = select(SuggestionEvaluation).join(ParameterSuggestion).where(
        ParameterSuggestion.user_id == user_id
    )
    if last_seen_eval:
        q_eval = q_eval.where(SuggestionEvaluation.created_at > last_seen_eval)
        
    evals = (await db.execute(q_eval)).scalars().all()
    count_eval = len(evals)
    
    if count_eval > 0:
        items.append({
             "type": "evaluation_ready",
             "count": count_eval,
             "title": "Impacto disponible",
             "message": f"Hay {count_eval} evaluación{'es' if count_eval>1 else ''} de impacto list{'as' if count_eval>1 else 'a'}.",
             "route": "#/suggestions?tab=accepted",
             "unread": True,  # Always unread if appearing here per logic
             "priority": "high"
        })
        
    # --- Check 3: Basal Review Today ---
    # Key: basal_review_YYYY-MM-DD
    today_str = date.today().isoformat()
    key_today = f"basal_review_{today_str}"
    
    if key_today not in state_map:
        # Not seen yet. Check advice.
        advice = await get_advice_service(user_id, 3, db)
        msg = advice.get("message", "")
        
        # Condition: message starts with "Revisa" (or contains it per prompt "tipo 'Revisa tu basal...'")
        if "Revisa" in msg:
            items.append({
                "type": "basal_review_today",
                "count": 1,
                "title": "Basal a revisar",
                "message": msg,
                "route": "#/basal",
                "unread": True,
                "priority": "high"
            })

    # --- Check 4: Shadow Labs Ready (Beta) ---
    # Condition: Confidence > 80% AND Feature Disabled AND Not recently dismissed
    from app.services.settings_service import get_user_settings_service
    settings_data = await get_user_settings_service(user_id, db)
    
    shadow_enabled = False
    if settings_data and settings_data.get("settings"):
        # We need to parse deep json
        try:
            shadow_enabled = settings_data["settings"].get("labs", {}).get("shadow_mode_enabled", False)
        except: pass
    
    if not shadow_enabled:
        # Check logs confidence
        from app.models.learning import ShadowLog
        # Fetch last 20 logs
        q_logs = (
            select(ShadowLog)
            .where(ShadowLog.user_id == user_id)
            .order_by(ShadowLog.created_at.desc())
            .limit(20)
        )
        logs = (await db.execute(q_logs)).scalars().all()
        
        if len(logs) >= 20: # Rigid Sample Size (Safety First)
            success_count = len([l for l in logs if l.status == 'success'])
            # Safety Check: ZERO failures allowed in the sample window
            # We assume 'neutral' is okay, but 'failed' (worse outcome) is a dealbreaker.
            failures = len([l for l in logs if l.status == 'failed' or l.status == 'danger'])
            
            if failures == 0:
                conf = (success_count / len(logs)) * 100
                
                if conf >= 80:
                    # Check if seen/dismissed recently
                    key_shadow = "shadow_labs_ready"
                    last_seen_shadow = state_map.get(key_shadow)
                    
                    if not last_seen_shadow:
                        items.append({
                            "type": "shadow_labs_ready",
                            "count": 1,
                            "title": "⚡ Labs: Auto-Absorción",
                            "message": f"Tu análisis de sombra es seguro (0 fallos en 20 test) y fiable ({int(conf)}%). Actívalo en Ajustes.",
                            "route": "#/settings",
                            "unread": True,
                            "priority": "low"
                        })
            
    # --- Check 5: Smart Post-Prandial Guardian (Pen Friendly) ---
    # Trigger: Meal ~2h ago AND High BG AND No Recent bolus (last 45m)
    # 1. Find Meal Bolus in [Now-2.5h, Now-1.5h]
    from app.models.treatment import Treatment
    from datetime import timedelta
    
    # DB timestamps are naive UTC usually
    window_start = datetime.utcnow() - timedelta(minutes=150) # 2.5h ago
    window_end = datetime.utcnow() - timedelta(minutes=90)    # 1.5h ago
    
    q_meal = (
        select(Treatment)
        .where(
            Treatment.user_id == user_id,
            Treatment.created_at >= window_start,
            Treatment.created_at <= window_end,
            Treatment.carbs > 20 # Only significant meals
        )
        .order_by(Treatment.created_at.desc())
        .limit(1)
    )
    last_meal = (await db.execute(q_meal)).scalars().first()
    
    if last_meal:
        # User ate ~2 hours ago. Check BG.
        # We need Nightscout Client. Resolve config.
        from app.services.nightscout_secrets_service import get_ns_config
        ns_config = await get_ns_config(db, user_id)
        
        if ns_config and ns_config.enabled and ns_config.url:
            current_bg = None
            trend = None
            try:
                # Quick fetch
                from app.services.nightscout_client import NightscoutClient
                async with NightscoutClient(ns_config.url, ns_config.api_secret, timeout_seconds=4) as client:
                    sgv = await client.get_latest_sgv()
                    if sgv:
                        current_bg = float(sgv.sgv)
                        trend = sgv.direction
            except Exception: pass
            
            if current_bg and current_bg > 180:
                # High Post Meal. 
                # INTELLIGENCE CHECKS:
                
                # 1. Trend Filter: If dropping fast, don't annoy.
                is_dropping = trend in ['DoubleDown', 'SingleDown', 'FortyFiveDown']
                if not is_dropping:
                    
                    # 2. "Recent Coverage" Filter (The Dual Bolus / Correction Detector)
                    # Check for ANY bolus in the last 60 mins.
                    recent_limit = datetime.utcnow() - timedelta(minutes=60)
                    q_recent = (
                        select(Treatment)
                        .where(
                            Treatment.user_id == user_id,
                            Treatment.created_at >= recent_limit,
                            Treatment.insulin > 0.5 # Minimal threshold
                        )
                    )
                    recent_bolus = (await db.execute(q_recent)).scalars().first()
                    
                    if not recent_bolus:
                        # CONDITION MET: High, Meal was long ago, No recent insulin.
                        # Unique Key for this alert (per meal id or per hour?)
                        key_alert = f"post_meal_alert_{last_meal.id}"
                        
                        if key_alert not in state_map:
                            items.append({
                                "type": "post_prandial_warning",
                                "count": 1,
                                "title": "⚠️ Revisión Post-Comida",
                                "message": f"Glucosa alta ({int(current_bg)}) 2h después de comer. ¿Olvidaste corregir o la 2ª dosis?",
                                "route": "#/bolus",
                                "unread": True,
                                "priority": "critical"
                            })

    # Summary
    has_unread = any(i.get("unread") for i in items)
    
    return {
        "has_unread": has_unread,
        "items": items
    }

async def mark_seen_service(types: list[str], user_id: str, db: AsyncSession):
    now = datetime.utcnow()
    
    for t in types:
        key = t
        if t == "basal_review_today":
            key = f"basal_review_{date.today().isoformat()}"
            
        # Upsert
        stmt = select(UserNotificationState).where(
            UserNotificationState.user_id == user_id,
            UserNotificationState.key == key
        )
        existing = (await db.execute(stmt)).scalars().first()
        
        if existing:
            existing.seen_at = now
        else:
            new_state = UserNotificationState(
                user_id=user_id,
                key=key,
                seen_at=now
            )
            db.add(new_state)
            
    await db.commit()
    return {"ok": True}
