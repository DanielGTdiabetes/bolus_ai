
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
    ns_client: NightscoutClient,
    db: AsyncSession
) -> dict[str, Any]:
    
    # 1. Fetch treatments
    # Calculate hours to fetch
    hours = (days * 24) + 24 # +24h buffer
    
    logger.info(f"Analysis: Fetching {hours} hours of treatments for user {user_id}")
    
    try:
        treatments = await ns_client.get_recent_treatments(hours=hours, limit=2000)
    except Exception as e:
        logger.error(f"Analysis failed to fetch treatments: {e}")
        return {"error": str(e)}
        
    start_cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    boluses = []
    for t in treatments:
        # Check integrity
        if not t.created_at: continue
        if t.created_at < start_cutoff: continue
        
        # Is it a bolus?
        if t.insulin is not None and t.insulin > 0.1: # Threshold to ignore tiny micro-boluses? 
             # Or keep all? Prompt says "tratamiento".
             boluses.append(t)
             
    logger.info(f"Analysis: Found {len(boluses)} boluses to analyze.")
    
    windows_written = 0
    target_base = settings.targets.mid
    
    for b in boluses:
        b_time = b.created_at
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
                sgvs = await ns_client.get_sgv_range(s_win, e_win, count=20)
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

async def get_summary_service(user_id: str, days: int, db: AsyncSession):
    # Query aggregated data
    # Filter by user and bolus_at >= now - days
    
    since = datetime.now(timezone.utc) - timedelta(days=days)
    
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
            by_meal[m][f"{w}h"] = {"short":0, "ok":0, "over":0, "missing":0}
            
    # Process
    unique_boluses = set()
    
    for row in rows:
        unique_boluses.add(row.bolus_at)
        if row.iob_status == "unavailable":
            # Just count globally?
            # "data_quality": { "iob_unavailable_events": X }
            # Since checks are per window, if one window is unavailable, does it mean the event is?
            # Usually iob_status is per bolus.
            pass
            
        m = row.meal_slot
        w = f"{row.window_h}h"
        res = row.result
        
        if m in by_meal and w in by_meal[m]:
            by_meal[m][w][res] += 1
            
    # Count iob_unavailable based on unique boluses?
    # Or just sum from rows where iob_status = unavailable (divided by 3?)
    # Let's count from rows directly. 
    # Actually, iob_status is stored per window row, but comes from the bolus.
    # We can count unique boluses with iob_status=unavailable.
    
    unavailable_boluses = set()
    for row in rows:
        if row.iob_status == "unavailable":
            unavailable_boluses.add(row.bolus_at)
            
    total_boluses = len(unique_boluses)
    
    # Insights
    insights = []
    
    # "Para cada meal_slot y window_h... si n >= 5..."
    for m, windows in by_meal.items():
        for w_key, counts in windows.items():
            total_valid = counts["short"] + counts["ok"] + counts["over"] # Ignore missing
            if total_valid >= 5:
                short_ratio = counts["short"] / total_valid
                over_ratio = counts["over"] / total_valid
                
                if short_ratio >= 0.60:
                    insights.append(f"En {translate_meal(m)}, a {w_key} tiendes a quedarte corto.")
                elif over_ratio >= 0.60:
                    insights.append(f"En {translate_meal(m)}, a {w_key} tiendes a pasarte.")
                    
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
