import uuid
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy import text
from app.core.db import get_engine
import logging

logger = logging.getLogger(__name__)

# Fallback in-memory storage if DB is not active
_mem_doses = []
# ... (existing imports)

# Fallback in-memory storage if DB is not active
_mem_doses = []
_mem_checkins = {} # (user_id, day) -> dict
_mem_night_summaries = {} # (user_id, night_date) -> dict
_mem_notes = []

# ... (existing functions: upsert_basal_dose, get_latest_basal_dose, upsert_daily_checkin, list_checkins, get_dose_history)

async def upsert_night_summary(user_id: str, night_date: date, had_hypo: bool, min_bg: int, events_hypo: int) -> Dict[str, Any]:
    entry_id = str(uuid.uuid4())
    now = datetime.utcnow()
    
    if get_engine():
        query = text("""
            INSERT INTO basal_night_summary (id, user_id, night_date, had_hypo, min_bg_mgdl, events_below_70, created_at)
            VALUES (:id, :user_id, :nd, :hypo, :min_bg, :ev_hypo, :now)
            ON CONFLICT (user_id, night_date) DO UPDATE
            SET had_hypo = EXCLUDED.had_hypo,
                min_bg_mgdl = EXCLUDED.min_bg_mgdl,
                events_below_70 = EXCLUDED.events_below_70,
                created_at = EXCLUDED.created_at
            RETURNING *
        """)
        params = {
            "id": entry_id,
            "user_id": user_id,
            "nd": night_date,
            "hypo": had_hypo,
            "min_bg": min_bg,
            "ev_hypo": events_hypo,
            "now": now
        }
        async with get_engine().begin() as conn:
            result = await conn.execute(query, params)
            row = result.fetchone()
            return dict(row._mapping) if row else None
    else:
        key = (user_id, night_date)
        entry = {
            "id": entry_id,
            "user_id": user_id,
            "night_date": night_date,
            "had_hypo": had_hypo,
            "min_bg_mgdl": min_bg,
            "events_below_70": events_hypo,
            "created_at": now
        }
        _mem_night_summaries[key] = entry
        return entry

async def list_night_summaries(user_id: str, days: int = 7) -> List[Dict[str, Any]]:
    if get_engine():
        query = text("""
            SELECT * FROM basal_night_summary
            WHERE user_id = :user_id
            ORDER BY night_date DESC
            LIMIT :limit
        """)
        async with get_engine().connect() as conn:
            result = await conn.execute(query, {"user_id": user_id, "limit": days})
            rows = result.fetchall()
            return [dict(r._mapping) for r in rows]
    else:
        user_sums = [v for k,v in _mem_night_summaries.items() if k[0] == user_id]
        sorted_sums = sorted(user_sums, key=lambda x: x["night_date"], reverse=True)
        return sorted_sums[:days]

async def upsert_basal_dose(user_id: str, dose_u: float, effective_from: date = None, created_at: datetime = None) -> Dict[str, Any]:
    if effective_from is None:
        effective_from = date.today()
    
    entry_id = str(uuid.uuid4())
    # Use provided time or now
    saved_at = created_at if created_at else datetime.utcnow()
    
    if get_engine():
        # PostgreSQL
        query = text("""
            INSERT INTO basal_dose (id, user_id, dose_u, effective_from, created_at)
            VALUES (:id, :user_id, :dose_u, :effective_from, :created_at)
            RETURNING id, user_id, dose_u, effective_from, created_at
        """)
        params = {
            "id": entry_id,
            "user_id": user_id,
            "dose_u": dose_u,
            "effective_from": effective_from,
            "created_at": saved_at
        }
        async with get_engine().begin() as conn:
            result = await conn.execute(query, params)
            row = result.fetchone()
            if row:
                return dict(row._mapping)
    else:
        # In-Memory
        entry = {
            "id": entry_id,
            "user_id": user_id,
            "dose_u": dose_u,
            "effective_from": effective_from,
            "created_at": saved_at
        }
        _mem_doses.append(entry)
        return entry

async def get_latest_basal_dose(user_id: str) -> Optional[Dict[str, Any]]:
    if get_engine():
        query = text("""
            SELECT * FROM basal_dose 
            WHERE user_id = :user_id 
            ORDER BY effective_from DESC, created_at DESC 
            LIMIT 1
        """)
        async with get_engine().connect() as conn:
            result = await conn.execute(query, {"user_id": user_id})
            row = result.fetchone()
            return dict(row._mapping) if row else None
    else:
        user_doses = [d for d in _mem_doses if d["user_id"] == user_id]
        if not user_doses:
            return None
        # Sort by effective_from desc, then created_at desc
        return sorted(user_doses, key=lambda x: (x["effective_from"], x["created_at"]), reverse=True)[0]

async def upsert_daily_checkin(user_id: str, day: date, bg_mgdl: float, trend: str, age_min: int, source: str) -> Dict[str, Any]:
    entry_id = str(uuid.uuid4())
    now = datetime.utcnow()
    
    if get_engine():
        # Uses ON CONFLICT on (user_id, checkin_date) assuming unique constraint exists per user request
        # Use 'day' column as primary date to satisfy constraint, keeping 'checkin_date' if it exists or aliases
        query = text("""
            INSERT INTO basal_checkin (id, user_id, checkin_date, bg_mgdl, trend, age_min, source, created_at)
            VALUES (:id, :user_id, :day, :bg, :trend, :age, :src, :now)
            ON CONFLICT (user_id, checkin_date) DO UPDATE
            SET bg_mgdl = EXCLUDED.bg_mgdl,
                trend = EXCLUDED.trend,
                age_min = EXCLUDED.age_min,
                source = EXCLUDED.source,
                created_at = EXCLUDED.created_at,
                checkin_date = EXCLUDED.checkin_date
            RETURNING *
        """)
        params = {
            "id": entry_id,
            "user_id": user_id,
            "day": day,
            "bg": bg_mgdl,
            "trend": trend,
            "age": age_min,
            "src": source,
            "now": now
        }
        async with get_engine().begin() as conn:
            result = await conn.execute(query, params)
            row = result.fetchone()
            return dict(row._mapping) if row else None
    else:
        key = (user_id, day)
        entry = {
            "id": entry_id,
            "user_id": user_id,
            "checkin_date": day,
            "bg_mgdl": bg_mgdl,
            "trend": trend,
            "age_min": age_min,
            "source": source,
            "created_at": now
        }
        _mem_checkins[key] = entry
        return entry

async def list_checkins(user_id: str, days: int = 14) -> List[Dict[str, Any]]:
    if get_engine():
        query = text("""
            SELECT * FROM basal_checkin
            WHERE user_id = :user_id
            ORDER BY checkin_date DESC
            LIMIT :limit
        """)
        async with get_engine().connect() as conn:
            result = await conn.execute(query, {"user_id": user_id, "limit": days})
            rows = result.fetchall()
            return [dict(r._mapping) for r in rows]
    else:
        user_checks = [v for k,v in _mem_checkins.items() if k[0] == user_id]
        sorted_checks = sorted(user_checks, key=lambda x: x["checkin_date"], reverse=True)
        return sorted_checks[:days]

async def get_dose_history(user_id: str, days: int = 30) -> List[Dict[str, Any]]:
    if get_engine():
        query = text("""
            SELECT * FROM basal_dose
            WHERE user_id = :user_id
            AND effective_from >= :start_date
            ORDER BY effective_from ASC
        """)
        # Calculate start date
        start_date = date.today() - timedelta(days=days)
        
        async with get_engine().connect() as conn:
            result = await conn.execute(query, {"user_id": user_id, "start_date": start_date})
            rows = result.fetchall()
            return [dict(r._mapping) for r in rows]
    else:
        # In-Memory
        cutoff = date.today() - timedelta(days=days)
        user_doses = [d for d in _mem_doses if d["user_id"] == user_id and d["effective_from"] >= cutoff]
        return sorted(user_doses, key=lambda x: x["effective_from"])

async def delete_old_data(retention_days: int = 90) -> dict:
    """
    Deletes data older than retention_days from all basal-related tables.
    """
    cutoff_date = date.today() - timedelta(days=retention_days)
    # For timestamp fields we can use datetime
    cutoff_datetime = datetime.utcnow() - timedelta(days=retention_days)
    
    deleted_counts = {}
    
    if get_engine():
        async with get_engine().begin() as conn:
            # 1. Basal Entries (Doses)
            # using effective_from or created_at. effective_from is safer for history.
            q1 = text("DELETE FROM basal_dose WHERE effective_from < :cutoff")
            r1 = await conn.execute(q1, {"cutoff": cutoff_date})
            deleted_counts["basal_dose"] = r1.rowcount
            
            # 2. Checkins
            q2 = text("DELETE FROM basal_checkin WHERE checkin_date < :cutoff")
            r2 = await conn.execute(q2, {"cutoff": cutoff_date})
            deleted_counts["basal_checkin"] = r2.rowcount
            
            # 3. Night Summaries
            q3 = text("DELETE FROM basal_night_summary WHERE night_date < :cutoff")
            r3 = await conn.execute(q3, {"cutoff": cutoff_date})
            deleted_counts["basal_night_summary"] = r3.rowcount
            
            # 4. Advice Daily (if exists)
            # Check if table exists first or just try? 
            # We know it exists from models, but maybe not migration. assuming yes.
            try:
                q4 = text("DELETE FROM basal_advice_daily WHERE advice_date < :cutoff")
                r4 = await conn.execute(q4, {"cutoff": cutoff_date})
                deleted_counts["basal_advice_daily"] = r4.rowcount
            except Exception as e:
                logger.warning(f"Cleanup advice failed (maybe table missing): {e}")
                deleted_counts["basal_advice_daily"] = 0

            # 5. Evaluations (if exists)
            try:
                q5 = text("DELETE FROM basal_change_evaluation WHERE change_at < :cutoff_dt")
                r5 = await conn.execute(q5, {"cutoff_dt": cutoff_datetime})
                deleted_counts["basal_change_evaluation"] = r5.rowcount
            except Exception as e:
                logger.warning(f"Cleanup evaluations failed: {e}")
                deleted_counts["basal_change_evaluation"] = 0
                
        logger.info(f"Data Cleanup Completed. Deleted: {deleted_counts}")
        return deleted_counts
    else:
        # In-Memory Cleanup
        # Note: In-memory is volatile anyway, but for correctness:
        initial_doses = len(_mem_doses)
        # Modify list in place or slice
        # Global _mem_doses need to be updated.
        # This is tricky with global variable imports. 
        # But we modify the content of lists/dicts.
        
        # Doses
        new_doses = [d for d in _mem_doses if d["effective_from"] >= cutoff_date]
        del_doses = len(_mem_doses) - len(new_doses)
        _mem_doses[:] = new_doses # Update in place
        
        # Checkins (dict keys)
        keys_to_del = [k for k, v in _mem_checkins.items() if v["checkin_date"] < cutoff_date]
        for k in keys_to_del:
            del _mem_checkins[k]
            
        # Night Summaries
        keys_night = [k for k, v in _mem_night_summaries.items() if v["night_date"] < cutoff_date]
        for k in keys_night:
            del _mem_night_summaries[k]

        return {
            "basal_dose": del_doses,
            "basal_checkin": len(keys_to_del),
            "basal_night_summary": len(keys_night),
            "mode": "memory"
        }
