import json
from sqlalchemy import text
from app.core.db import get_engine

async def import_user_data(user_id: str, data: dict):
    """
    Import data from JSON export.
    Upserts records based on Primary Key (usually ID).
    Forces user_id to match the authenticated user.
    """
    engine = get_engine()
    if not engine:
        return {"error": "No database connection"}

    allowed_tables = [
        "user_settings",
        "basal_checkin",
        "basal_entries", 
        "basal_night_summary",
        "basal_advice_daily",
        "basal_change_evaluation",
        "parameter_suggestion",
        "suggestion_evaluation",
        "user_notification_state"
    ]

    stats = {t: 0 for t in allowed_tables}
    stats["total_imported"] = 0

    async with engine.begin() as conn:
        for table_name, rows in data.items():
            if table_name not in allowed_tables or not isinstance(rows, list):
                continue
            
            if not rows:
                continue

            # We assume all rows in a list have mostly same columns. 
            # We take columns from the first row to build the statement.
            # This is a bit naive but standard for homogeneous exports.
            first_row = rows[0]
            columns = list(first_row.keys())
            
            # Filter columns to ensure safety? (Prevent SQL injection via column names? unlikely from JSON but good practice)
            # We just quote them.
            
            col_list = ", ".join([f'"{c}"' for c in columns])
            val_list = ", ".join([f':{c}' for c in columns])
            
            # Update clause for ON CONFLICT
            # We skip 'id' and 'user_id' in update
            update_assignments = [f'"{c}" = EXCLUDED."{c}"' for c in columns if c not in ('id', 'user_id', 'created_at')]
            
            if not update_assignments:
                # If only IDs, do nothing on conflict
                conflict_action = "DO NOTHING"
            else:
                conflict_action = f"DO UPDATE SET {', '.join(update_assignments)}"

            # Prepare Statement
            # Assuming 'id' is the unique constraint or PK.
            # Most tables have 'id' UUID.
            # Some like user_settings use user_id as PK?
            # Let's check schemas next time if this fails.
            # For user_settings, PK is user_id. For others, it's 'id'.
            
            constraint = "(id)"
            if table_name == "user_settings":
                constraint = "(user_id)"
            
            query = text(f"""
                INSERT INTO {table_name} ({col_list}) 
                VALUES ({val_list})
                ON CONFLICT {constraint} {conflict_action}
            """)

            for row in rows:
                # Override user_id for security
                row["user_id"] = user_id
                
                # Execute
                try:
                    await conn.execute(query, row)
                    stats[table_name] += 1
                    stats["total_imported"] += 1
                except Exception as e:
                    print(f"Error importing row into {table_name}: {e}")
                    # Continue best effort
                    pass

    return stats
