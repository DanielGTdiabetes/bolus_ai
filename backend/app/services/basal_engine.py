
import logging
from datetime import datetime, date, timedelta, time
from typing import Optional, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.basal import BasalEntry, BasalCheckin, BasalNightSummary, BasalAdviceDaily, BasalChangeEvaluation
from app.services.nightscout_client import NightscoutClient

logger = logging.getLogger(__name__)

async def upsert_checkin_service(user_id: str, checkin_date: date, bg: float, trend: str, db: AsyncSession):
    # Upsert Checkin
    # Check if exists
    stmt = select(BasalCheckin).where(
        BasalCheckin.user_id == user_id,
        BasalCheckin.checkin_date == checkin_date
    )
    res = await db.execute(stmt)
    existing = res.scalars().first()
    
    if existing:
        existing.bg_mgdl = bg
        existing.trend = trend
        existing.created_at = datetime.utcnow()
    else:
        new_entry = BasalCheckin(
            user_id=user_id,
            checkin_date=checkin_date,
            bg_mgdl=bg,
            trend=trend
        )
        db.add(new_entry)
        
    await db.commit()
    return {"status": "ok"}

async def scan_night_service(user_id: str, target_date: date, client: NightscoutClient, db: AsyncSession):
    # Window: 00:00 - 06:00 of target_date local time? 
    # Night of X usually means X evening to X+1 morning.
    # User said: "00:00–06:00 local".
    # Assuming target_date is the date OF THE MORNING.
    
    # We need timezone offset?
    # Nightscout stores UTC/Date. 
    # For now assume query by 'between' logic on simple date strings is risky if TZ differs.
    # But let's assume client handles it or we query wide and filter.
    
    # Date string YYYY-MM-DD
    # Start: YYYY-MM-DD T 00:00:00
    # End: YYYY-MM-DD T 06:00:00
    
    start_dt = datetime.combine(target_date, time(0, 0))
    end_dt = datetime.combine(target_date, time(6, 0))
    
    # Fetch entries from NS
    entries = await client.get_sgv_range(start_dt, end_dt, count=288)
    
    if not entries:
        # Maybe store empty summary?
        return {"status": "no_data"}
        
    bgs = [e.sgv for e in entries if e.sgv]
    if not bgs:
        return {"status": "no_sgv"}
        
    min_bg = min(bgs)
    below_70 = sum(1 for x in bgs if x < 70)
    had_hypo = below_70 > 0
    
    # Upsert Summary
    stmt = select(BasalNightSummary).where(
        BasalNightSummary.user_id == user_id,
        BasalNightSummary.night_date == target_date
    )
    res = await db.execute(stmt)
    existing = res.scalars().first()
    
    if existing:
        existing.had_hypo = had_hypo
        existing.min_bg_mgdl = min_bg
        existing.events_below_70 = below_70
        existing.created_at = datetime.utcnow()
    else:
        new_sum = BasalNightSummary(
            user_id=user_id,
            night_date=target_date,
            had_hypo=had_hypo,
            min_bg_mgdl=min_bg,
            events_below_70=below_70
        )
        db.add(new_sum)
        
    await db.commit()
    return {"status": "ok", "had_hypo": had_hypo, "min": min_bg}

async def get_timeline_service(user_id: str, days: int, db: AsyncSession):
    start_date = date.today() - timedelta(days=days)
    
    # Fetch Checkins
    q_check = select(BasalCheckin).where(
        BasalCheckin.user_id == user_id,
        BasalCheckin.checkin_date >= start_date
    ).order_by(BasalCheckin.checkin_date.desc())
    checkins = (await db.execute(q_check)).scalars().all()
    
    # Fetch Nights
    q_night = select(BasalNightSummary).where(
        BasalNightSummary.user_id == user_id,
        BasalNightSummary.night_date >= start_date
    ).order_by(BasalNightSummary.night_date.desc())
    nights = (await db.execute(q_night)).scalars().all()

    # Fetch Doses (BasalEntry in 'basal_dose' table usually)
    # The table is defined in models/basal.py as BasalEntry mapping to 'basal_dose'
    # We want valid doses in range.
    q_dose = select(BasalEntry).where(
        BasalEntry.user_id == user_id,
        BasalEntry.effective_from >= start_date
    ).order_by(BasalEntry.effective_from.desc(), BasalEntry.created_at.asc())
    doses = (await db.execute(q_dose)).scalars().all()
    
    # Combine by Date
    c_map = {c.checkin_date: c for c in checkins}
    n_map = {n.night_date: n for n in nights}
    
    # Doses map: (date -> dose_sum).
    d_map = {}
    for dose in doses:
        if dose.effective_from not in d_map:
             d_map[dose.effective_from] = 0.0
        d_map[dose.effective_from] += dose.dose_u
    
    items = []
    # Generate list for range
    for i in range(days):
        d = date.today() - timedelta(days=i)
        c = c_map.get(d)
        n = n_map.get(d)
        dose_val = d_map.get(d)
        
        items.append({
            "date": d.isoformat(),
            "dose_u": dose_val,
            "wake_bg": c.bg_mgdl if c else None,
            "wake_trend": c.trend if c else None,
            "night_had_hypo": n.had_hypo if n else None,
            "night_min_bg": n.min_bg_mgdl if n else None,
            "night_events_below_70": n.events_below_70 if n else 0
        })
        
    return {
        "days": days,
        "items": items,
        "data_quality": {
            "wake_days": len(checkins),
            "night_days": len(nights),
            "dose_days": len(d_map)
        }
    }

async def get_advice_service(user_id: str, days: int, db: AsyncSession):
    # Fetch data
    tl = await get_timeline_service(user_id, days, db)
    items = tl["items"]
    
    valid_checks = [i for i in items if i["wake_bg"] is not None]
    valid_nights = [i for i in items if i["night_had_hypo"] is not None]
    
    n_checks = len(valid_checks)
    n_nights = len(valid_nights)
    
    # Confidence
    confidence = "low"
    if n_checks >= 3 and n_nights >= 2:
        confidence = "high"
    elif n_checks >= 1 and n_nights >= 1:
        confidence = "medium"
        
    # Logic
    message = "Basal OK"
    
    # Priority 1: Night Hypos
    night_hypos = sum(1 for n in valid_nights if n["night_had_hypo"])
    if night_hypos >= 2: # heuristic: more than 1 night with hypo
        message = f"Revisa tu basal: hipoglucemias nocturnas detectadas en {night_hypos} noches."
    elif night_hypos == 1:
        message = "Revisa tu basal: detectada hipoglucemia nocturna."
    else:
        # Priority 2: Wake Trend
        if n_checks >= 2:
            avg_wake = sum(i["wake_bg"] for i in valid_checks) / n_checks
            if avg_wake > 130:
                 message = "Revisa tu basal: glucosa en ayunas alta (>130 mg/dL)."
            elif avg_wake < 80:
                 # Check if dropping
                 message = "Revisa tu basal: glucosa en ayunas baja (<80 mg/dL)."
                 
    return {
        "message": message,
        "confidence": confidence,
        "stats": {
            "avg_wake": round(sum(i["wake_bg"] for i in valid_checks) / n_checks, 0) if n_checks else None,
            "night_hypos": night_hypos
        }
    }

async def evaluate_change_service(user_id: str, days: int, db: AsyncSession):
    # Find last change point by looking at daily totals
    # Fetch enough history to find a change
    
    q_dose = select(BasalEntry).where(
        BasalEntry.user_id == user_id
    ).order_by(BasalEntry.effective_from.desc())
    doses = (await db.execute(q_dose)).scalars().all()
    
    # Aggregate by date
    by_date = {}
    for d in doses:
        if d.effective_from not in by_date: by_date[d.effective_from] = 0.0
        by_date[d.effective_from] += d.dose_u
        
    dates = sorted(by_date.keys(), reverse=True)
    if len(dates) < 2:
        return {"result": "insufficient", "summary": "No hay suficientes datos diarios.", "evidence": {}}
        
    # Find change
    current_total = by_date[dates[0]]
    change_date = None
    prev_total = None
    
    for i in range(1, len(dates)):
        d = dates[i]
        t = by_date[d]
        if abs(t - current_total) > 0.5: # Change detected
            change_date = dates[0] # The change happened ON the new regime start
            prev_total = t
            # Actually, the change effective date is dates[0] presumably if that's the start of new regime.
            # But if there are gaps? Assuming continuous.
            # Let's verify if dates[0] is recent.
            # If dates[0] is today and dates[1] was yesterday and they differ, change was today.
            change_date = dates[0] # Use the LATEST date as the start of new regime
            break
            
    if change_date is None:
         # No change found in history
         return {"result": "insufficient", "summary": "Dosis estable, sin cambios recientes.", "evidence": {}}

    # Define Periods
    # Before: [change_date - days, change_date)
    # After: [change_date, change_date + days)
    
    start_before = change_date - timedelta(days=days)
    end_after = change_date + timedelta(days=days)
    
    # Helper to get stats
    async def get_stats(d_start, d_end):
        # Wake BG
        q_c = select(BasalCheckin).where(
            BasalCheckin.user_id == user_id,
            BasalCheckin.checkin_date >= d_start,
            BasalCheckin.checkin_date < d_end
        )
        checks = (await db.execute(q_c)).scalars().all()
        
        # Night Hypos
        q_n = select(BasalNightSummary).where(
            BasalNightSummary.user_id == user_id,
            BasalNightSummary.night_date >= d_start,
            BasalNightSummary.night_date < d_end
        )
        nights = (await db.execute(q_n)).scalars().all()
        
        n_c = len(checks)
        if n_c == 0:
            return None
            
        mean_wake = sum(c.bg_mgdl for c in checks) / n_c
        over_130 = sum(1 for c in checks if c.bg_mgdl > 130) / n_c
        under_80 = sum(1 for c in checks if c.bg_mgdl < 80) / n_c
        
        n_map = {n.night_date: n for n in nights}
        # Check hypos for dates covered by checkins or all dates in range?
        # User implies period total.
        hypos = sum(1 for n in nights if n.had_hypo)
        
        return {
            "n": n_c,
            "mean_wake": mean_wake,
            "pct_over_130": over_130,
            "pct_under_80": under_80,
            "night_hypos": hypos
        }

    before = await get_stats(start_before, change_date)
    after = await get_stats(change_date, end_after)

    if not before or before["n"] < 4:
        return {"result": "insufficient", "summary": f"Faltan datos previos (n={before['n'] if before else 0}, min 4).", "evidence": {}}
    
    if not after:
        # Check if enough time passed?
        # Or just not enough data
        return {"result": "insufficient", "summary": "Faltan datos posteriores.", "evidence": {}}
        
    if after["n"] < 4:
        return {"result": "insufficient", "summary": f"Datos posteriores insuficientes (n={after['n']}, min 4).", "evidence": {}}
         
    # Scoring
    # score = %over + %under + (1 if hypos>=2 else 0)
    # Lower is better
    
    def calc_score(s):
        flag = 1.0 if s["night_hypos"] >= 2 else 0.0
        return s["pct_over_130"] + s["pct_under_80"] + flag
        
    s_before = calc_score(before)
    s_after = calc_score(after)
    
    summary = ""
    result = "no_change"
    
    delta = 0.15
    if s_after <= s_before - delta:
        result = "improved"
        summary = f"Mejoró: bajó inestabilidad ({round(s_before,2)} -> {round(s_after,2)})."
    elif s_after >= s_before + delta:
        result = "worse"
        summary = f"Empeoró: aumentó inestabilidad ({round(s_before,2)} -> {round(s_after,2)})."
    else:
        # Secondary check: mean wake
        if (before["mean_wake"] - after["mean_wake"]) >= 10:
             # Improved mean wake
             # BUT check hypos
             if after["night_hypos"] > before["night_hypos"]:
                 result = "worse" # Tradeoff bad
                 summary = "Bajó media pero aumentaron hipos nocturnas."
             else:
                 result = "improved"
                 summary = f"Mejoró media despertar ({int(before['mean_wake'])} -> {int(after['mean_wake'])})."
    
    if result == "no_change":
        summary = "Sin cambios significativos."
        
    # Save Evaluation
    eval_entry = BasalChangeEvaluation(
        user_id=user_id,
        change_at=datetime.combine(change_date, time(0,0)), 
        from_dose_u=prev_total,
        to_dose_u=current_total,
        days=days,
        result=result,
        summary=summary,
        evidence={
            "before": before,
            "after": after,
            "score_before": s_before,
            "score_after": s_after
        }
    )
    db.add(eval_entry)
    await db.commit()
    
    return {
        "result": result,
        "summary": summary,
        "evidence": {
            "before": before,
            "after": after,
            "score_before": s_before,
            "score_after": s_after
        }
    }
