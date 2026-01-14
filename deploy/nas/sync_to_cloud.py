
import os
import sys
import logging
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Config
LOCAL_DB_URL = os.getenv("DATABASE_URL")
CLOUD_DB_URL = os.getenv("CLOUD_DATABASE_URL") # User must set this in NAS .env

# Sync Policy: Keep last N days active in cloud
SYNC_DAYS = 30

TABLES_TO_SYNC = [
    # Table Name, Date Column (None if full sync needed), ID Column
    ("users", None, "username"), 
    # Add other configuration tables here if they exist and are small
    # ("user_settings", "updated_at", "user_id"), 
    
    # Transactional Data (Windowed)
    ("treatments", "created_at", "id"),
    ("meal_entries", "created_at", "id"),
    ("basal_dose", "effective_from", "id"),
    ("basal_checkin", "checkin_date", "id"),
    ("favorite_foods", None, "id"),
]

async def sync_table(local_conn, cloud_conn, table_name, date_col, id_col):
    logger.info(f"Syncing table: {table_name}...")
    
    # 1. Select Data from Local
    if date_col:
        cutoff = datetime.utcnow() - timedelta(days=SYNC_DAYS)
        query = text(f"SELECT * FROM {table_name} WHERE {date_col} >= :cutoff")
        result = await local_conn.execute(query, {"cutoff": cutoff})
    else:
        query = text(f"SELECT * FROM {table_name}")
        result = await local_conn.execute(query)
    
    rows = result.fetchall()
    if not rows:
        logger.info(f"  -> No rows to sync for {table_name}.")
        return

    logger.info(f"  -> Found {len(rows)} rows locally.")

    # 2. Insert to Cloud (Upsert)
    # We construct a dynamic INSERT ON CONFLICT statement
    # This assumes both DBs have same schema.
    
    keys = result.keys()
    cols = ", ".join(keys)
    vals_placeholders = ", ".join([f":{k}" for k in keys])
    
    # Update clause for Upsert
    update_clause = ", ".join([f"{k} = EXCLUDED.{k}" for k in keys if k != id_col])
    
    if not update_clause:
        # If table has only ID column (rare), do nothing on conflict
        sql = f"""
            INSERT INTO {table_name} ({cols}) VALUES ({vals_placeholders})
            ON CONFLICT ({id_col}) DO NOTHING
        """
    else:
        sql = f"""
            INSERT INTO {table_name} ({cols}) VALUES ({vals_placeholders})
            ON CONFLICT ({id_col}) DO UPDATE SET {update_clause}
        """

    # Batch execution
    count = 0
    try:
        # Convert rows to dicts for parameter binding
        # row._mapping gives dict access in SQLAlchemy 1.4+
        data = [dict(row._mapping) for row in rows]
        
        await cloud_conn.execute(text(sql), data)
        await cloud_conn.commit()
        count = len(data)
    except Exception as e:
        logger.error(f"  -> Failed to push batch to cloud: {e}")
        await cloud_conn.rollback()
        return

    logger.info(f"  -> Successfully synced {count} rows to Cloud.")

async def main():
    if not LOCAL_DB_URL or not CLOUD_DB_URL:
        logger.error("Missing DATABASE_URL or CLOUD_DATABASE_URL environment variables.")
        return

    # Create Engines
    # Ensure we use async drivers (postgresql+asyncpg)
    local_url = LOCAL_DB_URL.replace("postgresql://", "postgresql+asyncpg://") if "asyncpg" not in LOCAL_DB_URL else LOCAL_DB_URL
    cloud_url = CLOUD_DB_URL.replace("postgresql://", "postgresql+asyncpg://") if "asyncpg" not in CLOUD_DB_URL else CLOUD_DB_URL

    local_eng = create_async_engine(local_url, echo=False)
    cloud_eng = create_async_engine(cloud_url, echo=False)

    try:
        async with local_eng.connect() as l_conn, cloud_eng.connect() as c_conn:
            logger.info("Connected to both Local and Cloud DBs.")
            
            for table_info in TABLES_TO_SYNC:
                t_name, d_col, id_col = table_info
                try:
                    await sync_table(l_conn, c_conn, t_name, d_col, id_col)
                except Exception as e:
                    logger.error(f"Error processing table {t_name}: {e}")
                    
    except Exception as e:
        logger.critical(f"Global Sync Error: {e}")
    finally:
        await local_eng.dispose()
        await cloud_eng.dispose()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
