from datetime import date, datetime
import uuid
from sqlalchemy import text
from app.core.db import _async_engine, _in_memory_store

async def export_all_user_data(user_id: str):
    # In-Memory Fallback
    if not _async_engine:
        # Naive export from memory dicts if structured, but our _in_memory_store is simple
        # For this refactor, we focus on DB.
        return {
            "source": "memory", 
            "basal_checkins": [c for c in _in_memory_store.get("checkins", []) if getattr(c, "user_id", "") == user_id],
            "entries": [e for e in _in_memory_store.get("entries", []) if getattr(e, "user_id", "") == user_id]
        }

    # Dict of Table Name -> Sort Column
    tables = {
        "user_settings": "updated_at",
        "basal_checkin": "checkin_date",
        "basal_entries": "created_at",
        "basal_night_summary": "night_date",
        "basal_advice_daily": "advice_date",
        "basal_change_evaluation": "change_at",
        "parameter_suggestion": "generated_at",
        "suggestion_evaluation": "evaluated_at",
        "user_notification_state": "last_seen_at"
    }

    data = {"user_id": user_id, "export_date": datetime.utcnow().isoformat()}

    async with _async_engine.begin() as conn:
        for table, sort_col in tables.items():
            try:
                # Check if table exists to avoid crashes if migration didn't run for some
                # Better: try/except the query
                query = text(f"SELECT * FROM {table} WHERE user_id = :uid ORDER BY {sort_col} DESC")
                result = await conn.execute(query, {"uid": user_id})
                
                rows = []
                for row in result:
                    item = dict(row._mapping)
                    # Serialize
                    for k, v in item.items():
                        if isinstance(v, (datetime, date)):
                            item[k] = v.isoformat()
                        elif isinstance(v, uuid.UUID):
                            item[k] = str(v)
                    rows.append(item)
                
                data[table] = rows
            except Exception as e:
                data[table] = {"error": str(e), "note": "Table might not exist or empty"}
    
    return data
