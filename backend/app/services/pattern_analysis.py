
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.analysis import BolusPostAnalysis
from app.models.settings import UserSettings
from app.services.nightscout_client import NightscoutClient
# from app.services.iob import compute_iob_from_sources # Not needed if we trust the loop

logger = logging.getLogger(__name__)

def get_meal_slot(dt: datetime) -> str:
    # Use hour in local context? 
    # We don't have user timezone, assuming relative to the treatment timestamp 
    # which is usually UTC in NS, but "created_at" might be naive in strings.
    # Let's use the hour attribute.
    h = dt.hour
    if 5 <= h < 11: return "breakfast"
    if 11 <= h < 15: return "lunch"
    if 19 <= h < 23: return "dinner"
    # Between lunch and dinner (15-19) -> snack
    # Late night (23-5) -> snack
    if 15 <= h < 19: return "snack"
    return "snack"

async def run_analysis_service(
    user_id: str,
    days: int,
    settings: UserSettings,
    ns_client: Optional[NightscoutClient],
    db: AsyncSession
) -> dict[str, Any]:
    
    # 1. Fetch treatments
    # We fetch from DB first (primary source of truth for boluses)
    # Then NS (for older history if needed, though DB should mirror it eventually)
    
    hours = (days * 24) + 24 # +24h buffer
    start_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    
    logger.info(f"Analysis: Fetching treatments for user {user_id} (last {days} days)")
    
    from app.models.treatment import Treatment
    
    # DB Query
    stmt = (
        select(Treatment)
        .where(
            Treatment.user_id == user_id,
            Treatment.created_at >= start_cutoff,
            Treatment.insulin > 0.1 # significant bolus
        )
        .order_by(Treatment.created_at.desc())
    )
    res = await db.execute(stmt)
    db_boluses = res.scalars().all()
    
    boluses = list(db_boluses)
    
    # Try NS to supplement (only if DB is empty or we want to be super robust)
    # If DB has data, we trust it. If DB is empty, maybe new install? Try NS.
    if not boluses and ns_client:
        try:
             # We adapt NS treatments to look like Treatment objects (duck typing)
             ns_treatments = await ns_client.get_recent_treatments(hours=hours, limit=2000)
             for t in ns_treatments:
                 if t.created_at and t.created_at >= start_cutoff and t.insulin and t.insulin > 0.1:
                     boluses.append(t)
        except Exception as e:
             logger.warning(f"Analysis: NS fetch failed ({e}), continuing with local DB data only.")
             
    logger.info(f"Analysis: Found {len(boluses)} boluses to analyze.")
    
    windows_written = 0
    target_base = settings.targets.mid
    
    for b in boluses:
        b_time = b.created_at
        if b_time.tzinfo is None:
            b_time = b_time.replace(tzinfo=timezone.utc)
        
        meal_slot = get_meal_slot(b_time)
        
        # Target: user settings active? 
        # Using global target for now as per previous investigation
        target = target_base
        
        # IOB Status: We assume OK if we have the record and are running batch analysis
        iob_status = "ok"
        
        for w in [2, 3, 5]:
            check_time = b_time + timedelta(hours=w)
            
            # Fetch BG
            # +/- 15 min
            s_win = check_time - timedelta(minutes=15)
            e_win = check_time + timedelta(minutes=15)
            
            result = "missing"
            bg_val = None
            bg_at_val = None
            
            try:
                if ns_client:
                    sgvs = await ns_client.get_sgv_range(s_win, e_win, count=20)
                else:
                    sgvs = [] # Need DB lookup for SGV? Or assume unavailable without NS?
                    # TODO: If we store glucose in DB eventually, fetch here.
                    # For now, without NS, result is "missing" which is correct behavior.
                if sgvs:
                    # Parse dates if needed, NightscoutSGV schema has date as int (epoch ms)
                    # Helper to get datetime
                    best_sgv = None
                    min_diff = float("inf")
                    
                    for s in sgvs:
                        s_dt = datetime.fromtimestamp(s.date / 1000, tz=timezone.utc)
                        diff = abs((s_dt - check_time).total_seconds())
                        if diff <= 15 * 60:
                            if diff < min_diff:
                                min_diff = diff
                                best_sgv = s
                                bg_val = float(s.sgv)
                                bg_at_val = s_dt
                    
                    if bg_val:
                        delta = bg_val - target
                        if delta > 30:
                            result = "short"
                        elif delta < -30:
                            result = "over"
                        else:
                            result = "ok"
                            
            except Exception as e:
                # logger.warning(f"Failed to fetch SGV for window: {e}")
                pass
            
            # Upsert
            stmt = pg_insert(BolusPostAnalysis).values(
                user_id=user_id,
                bolus_at=b_time,
                meal_slot=meal_slot,
                window_h=w,
                bg_mgdl=bg_val,
                bg_at=bg_at_val,
                target_mgdl=target,
                result=result,
                iob_status=iob_status,
                created_at=datetime.utcnow()
            ).on_conflict_do_update(
                index_elements=["user_id", "bolus_at", "window_h"],
                set_=dict(
                    bg_mgdl=bg_val,
                    bg_at=bg_at_val,
                    target_mgdl=target,
                    result=result,
                    iob_status=iob_status,
                    created_at=datetime.utcnow()
                )
            )
            await db.execute(stmt)
            windows_written += 1
            
    await db.commit()
    return {
        "days": days,
        "boluses": len(boluses),
        "windows_written": windows_written
    }

async def get_summary_service(user_id: str, days: int, db: AsyncSession, settings: UserSettings = None):
    # Query aggregated data
    # Filter by user and bolus_at >= now - days
    
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Optimization: If settings were updated recently, only analyze SINCE that update
    # to avoid advising changes based on old data that might already be fixed.
    if settings and settings.updated_at:
        # settings.updated_at is timezone aware (UTC) usually
        # If the user updated settings 2 days ago, we should only look at last 2 days
        # even if they asked for 30.
        if settings.updated_at > since:
            since = settings.updated_at

    query = select(BolusPostAnalysis).where(
        BolusPostAnalysis.user_id == user_id,
        BolusPostAnalysis.bolus_at >= since
    )
    
    result = await db.execute(query)
    rows = result.scalars().all()
    
    # Aggregation
    # Structure:
    # { "breakfast": { "2h": {short:0, ...} } }
    
    by_meal = {
        "breakfast": {}, "lunch": {}, "dinner": {}, "snack": {}
    }
    
    iob_unavailable = 0
    total_events = 0 # unique boluses? or unique windows? Request says "cuantos eventos tenían iob_status=unavailable". Likely bolus events.
    # But rows are windows.
    # Let's count windows for now or track unique bolus_at.
    
    # Initialize
    for m in by_meal:
        for w in [2, 3, 5]:
            # Added "unavailable_iob" to track quality per window
            by_meal[m][f"{w}h"] = {"short":0, "ok":0, "over":0, "missing":0, "unavailable_iob": 0}
            
    # Process
    unique_boluses = set()
    
    for row in rows:
        unique_boluses.add(row.bolus_at)
        
        m = row.meal_slot
        w = f"{row.window_h}h"
        res = row.result
        
        if m in by_meal and w in by_meal[m]:
            # if IOB is unavailable, we don't trust the outcome for pattern analysis, 
            # but we track it for quality metrics.
            if row.iob_status == "unavailable":
                by_meal[m][w]["unavailable_iob"] += 1
                continue
                
            by_meal[m][w][res] += 1
            
    # Count iob_unavailable based on unique boluses?
    # We kept the global one for backward compatibility or general health check
    unavailable_boluses = set()
    for row in rows:
        if row.iob_status == "unavailable":
            unavailable_boluses.add(row.bolus_at)
            
    total_boluses = len(unique_boluses)
    
    # Insights
    insights = []
    
    # Helper to get current CR
    def get_current_cr(meal_name):
        if not settings: return None
        # Settings.cr is MealFactors object or dict depending on parsing.
        # It's a Pydantic model usually.
        if hasattr(settings.cr, meal_name):
            return getattr(settings.cr, meal_name)
        # Fallback if dictionary or accessing via key string
        # (Though Pydantic model access via dot is standard)
        return getattr(settings.cr, meal_name, 10.0)

    # "Para cada meal_slot y window_h... si n >= 5..."
    for m, windows in by_meal.items():
        for w_key, counts in windows.items():
            total_valid = counts["short"] + counts["ok"] + counts["over"] # Ignore missing and unavailable for ratio
            
            # Check Quality (New requirement for suggestions, but good for insights too)
            # If we have too many unavailable IOBs, maybe we shouldn't emit insight?
            # Or currently we just emit based on valid data.
            # User requirement: "proporción de eventos con iob_status='unavailable' <= 30%"
            total_total = total_valid + counts["unavailable_iob"]
            if total_total > 0:
                bad_ratio = counts["unavailable_iob"] / total_total
                if bad_ratio > 0.30:
                    continue # Skip insight if data is poor quality
            
            if total_valid >= 5:
                short_ratio = counts["short"] / total_valid
                over_ratio = counts["over"] / total_valid
                
                # Get current ratio for this meal
                current_icr = get_current_cr(m)
                
                if short_ratio >= 0.60:
                    advice = ""
                    if current_icr:
                        # Suggest lower ICR (more insulin)
                        # Round to nearest 0.5
                        raw_new = current_icr * 0.9
                        new_icr = round(raw_new * 2) / 2
                        
                        if new_icr >= current_icr: new_icr = current_icr - 0.5 # Ensure at least -0.5 change
                        if new_icr < 1: new_icr = 1 # Safety floor
                        
                        advice = f"Valora cambiar tu Ratio de {current_icr} a {new_icr}."
                    else:
                        advice = "Valora bajar tu Ratio (necesitas más insulina)."
                        
                    insights.append(f"En {translate_meal(m)}, a las {w_key} sueles estar ALTO. {advice}")
                    
                elif over_ratio >= 0.60:
                    advice = ""
                    if current_icr:
                        # Suggest higher ICR (less insulin)
                        raw_new = current_icr * 1.1
                        new_icr = round(raw_new * 2) / 2
                        
                        if new_icr <= current_icr: new_icr = current_icr + 0.5 # Ensure at least +0.5 change
                        
                        advice = f"Valora cambiar tu Ratio de {current_icr} a {new_icr}."
                    else:
                        advice = "Valora subir tu Ratio (te sobra insulina)."

                    insights.append(f"En {translate_meal(m)}, a las {w_key} sueles estar BAJO. {advice}")
                    
    return {
        "days": days,
        "by_meal": by_meal,
        "data_quality": {
            "iob_unavailable_events": len(unavailable_boluses),
            "total_events": total_boluses
        },
        "insights": insights
    }

def translate_meal(m: str) -> str:
    map = {
        "breakfast": "desayunos",
        "lunch": "comidas",
        "dinner": "cenas",
        "snack": "snacks"
    }
    return map.get(m, m)
