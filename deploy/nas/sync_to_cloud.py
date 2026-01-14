import os
import sys
import logging
import asyncio
import time
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Config
LOCAL_DB_URL = os.getenv("DATABASE_URL")
CLOUD_DB_URL = os.getenv("CLOUD_DATABASE_URL") # User must set this in NAS .env
DRY_RUN = os.getenv("SYNC_DRY_RUN", "0") == "1"

# Sync Policy: Keep last N days active in cloud
SYNC_DAYS = 30
LOCK_FILE = "sync.lock"
LOCK_TTL_SECONDS = 3600

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

async def get_table_columns(conn, table_name):
    """Retorna un set con los nombres de las columnas de una tabla."""
    query = text("SELECT column_name FROM information_schema.columns WHERE table_name = :table AND table_schema = 'public'")
    result = await conn.execute(query, {"table": table_name})
    return {row[0] for row in result.fetchall()}

async def cleanup_old_data(cloud_conn, table_name, date_col):
    """Elimina datos antiguos en Neon para mantener la ventana de tiempo."""
    if not date_col:
        return 0
    
    logger.info(f"  -> Cleaning old data in {table_name} (older than {SYNC_DAYS} days)...")
    if DRY_RUN:
        logger.info("  -> [DRY RUN] Would execute DELETE query.")
        return 0

    cleanup_sql = text(f"""
        DELETE FROM {table_name} 
        WHERE {date_col} < NOW() - INTERVAL '{SYNC_DAYS} days'
    """)
    result = await cloud_conn.execute(cleanup_sql)
    await cloud_conn.commit()
    deleted_count = result.rowcount
    if deleted_count > 0:
        logger.info(f"  -> Deleted {deleted_count} old rows from Cloud.")
    return deleted_count

async def sync_table(local_conn, cloud_conn, table_name, date_col, id_col):
    logger.info(f"Syncing table: {table_name}...")
    start_time = time.monotonic()
    
    # 0. Safety: Get intersecting columns to avoid schema mismatch
    local_cols = await get_table_columns(local_conn, table_name)
    cloud_cols = await get_table_columns(cloud_conn, table_name)
    
    if not local_cols:
        logger.warning(f"  -> Table {table_name} does not exist locally. Skipping.")
        return
    if not cloud_cols:
        logger.warning(f"  -> Table {table_name} does not exist in Cloud. Skipping.")
        return

    # Deterministic column order for hygiene and logging consistency
    common_cols = sorted(list(local_cols.intersection(cloud_cols)))
    if not common_cols:
        logger.error(f"  -> No common columns for {table_name}. Skipping.")
        return
        
    # Ensure ID col is present
    if id_col not in common_cols:
        logger.error(f"  -> ID column {id_col} missing in common columns. Skipping.")
        return

    # 1. Cleanup Old Data in Cloud
    await cleanup_old_data(cloud_conn, table_name, date_col)

    # 2. Select Data from Local (Explicit columns)
    cols_list = ", ".join(common_cols)
    
    if date_col:
        cutoff = datetime.utcnow() - timedelta(days=SYNC_DAYS)
        query = text(f"SELECT {cols_list} FROM {table_name} WHERE {date_col} >= :cutoff")
        result = await local_conn.execute(query, {"cutoff": cutoff})
    else:
        query = text(f"SELECT {cols_list} FROM {table_name}")
        result = await local_conn.execute(query)
    
    rows = result.fetchall()
    if not rows:
        logger.info(f"  -> No rows to sync for {table_name}.")
        return

    logger.info(f"  -> Found {len(rows)} rows locally.")

    if DRY_RUN:
        logger.info(f"  -> [DRY RUN] Would insert/upsert {len(rows)} rows into Cloud.")
        elapsed = time.monotonic() - start_time
        logger.info(f"  -> Finished {table_name} in {elapsed:.2f}s (Dry Run)")
        return

    # 3. Insert to Cloud (Upsert) using ONLY common columns
    vals_placeholders = ", ".join([f":{k}" for k in common_cols])
    
    # Update clause for Upsert
    update_clause = ", ".join([f"{k} = EXCLUDED.{k}" for k in common_cols if k != id_col])
    
    if not update_clause:
        sql = f"""
            INSERT INTO {table_name} ({cols_list}) VALUES ({vals_placeholders})
            ON CONFLICT ({id_col}) DO NOTHING
        """
    else:
        sql = f"""
            INSERT INTO {table_name} ({cols_list}) VALUES ({vals_placeholders})
            ON CONFLICT ({id_col}) DO UPDATE SET {update_clause}
        """

    # Batch execution
    count = 0
    try:
        # Explicit dict creation ensuring only common keys are passed (safety double check)
        data = [{k: getattr(row, k) for k in common_cols} for row in rows]
        
        await cloud_conn.execute(text(sql), data)
        await cloud_conn.commit()
        count = len(data)
    except Exception as e:
        logger.error(f"  -> Failed to push batch to cloud: {e}")
        await cloud_conn.rollback()
        return

    elapsed = time.monotonic() - start_time
    logger.info(f"  -> Successfully synced {count} rows to Cloud in {elapsed:.2f}s.")

async def run_sync_once():
    """Logic of a single sync run, extracted from main."""
    LOCK_FILE = "sync.lock" # Define scope or use global constant
    
    # Check enviroment again if needed, or pass args. 
    # Logic copied from original main
    if not LOCAL_DB_URL or not CLOUD_DB_URL:
        logger.error("Missing DATABASE_URL or CLOUD_DATABASE_URL environment variables.")
        return

    if DRY_RUN:
        logger.info("=== STARTING SYNC IN DRY-RUN MODE ===")
        logger.info("No changes will be made to the Cloud DB.")
    
    # Lock Mechanism
    if os.path.exists(LOCK_FILE):
        try:
            mtime = os.path.getmtime(LOCK_FILE)
            age = datetime.now().timestamp() - mtime
            if age > LOCK_TTL_SECONDS:
                logger.warning(f"Found stale lock file (>{LOCK_TTL_SECONDS/3600}h). Removing and continuing.")
                os.remove(LOCK_FILE)
            else:
                logger.warning("Sync already running (lock file exists). Skipping this run.")
                return
        except OSError:
            pass

    with open(LOCK_FILE, 'w') as f:
        f.write(str(datetime.now()))

    try:
        # Create Engines
        local_url = LOCAL_DB_URL.replace("postgresql://", "postgresql+asyncpg://") if "asyncpg" not in LOCAL_DB_URL else LOCAL_DB_URL
        cloud_url = CLOUD_DB_URL.replace("postgresql://", "postgresql+asyncpg://") if "asyncpg" not in CLOUD_DB_URL else CLOUD_DB_URL

        local_eng = create_async_engine(local_url, echo=False)
        cloud_eng = create_async_engine(cloud_url, echo=False)

        async with local_eng.connect() as l_conn, cloud_eng.connect() as c_conn:
            logger.info("Connected to both Local and Cloud DBs.")
            
            for table_info in TABLES_TO_SYNC:
                t_name, d_col, id_col = table_info
                try:
                    await sync_table(l_conn, c_conn, t_name, d_col, id_col)
                except Exception as e:
                    logger.error(f"Error processing table {t_name}: {e}")
        
        logger.info("=== SYNC FINISHED SUCCESSFULLY ===")
                    
    except Exception as e:
        logger.critical(f"Global Sync Error: {e}")
    finally:
        if 'local_eng' in locals(): await local_eng.dispose()
        if 'cloud_eng' in locals(): await cloud_eng.dispose()
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)

async def main():
    # If SYNC_LOOP is True, run continuously (Service Mode)
    loop_mode = os.getenv("SYNC_LOOP", "0") == "1"
    
    if loop_mode:
        logger.info("🔄 Starting Sync Service in LOOP Mode")
        while True:
            # Check if enabled (Default: False/0)
            # This allows the container to run but stay idle by default
            is_enabled = os.getenv("SYNC_ENABLED", "0") == "1"
            
            if is_enabled:
                logger.info("⏰ Sync Enabled. Starting execution...")
                try:
                    await run_sync_once()
                except Exception as e:
                    logger.error(f"💥 Crash in sync loop: {e}")
            else:
                logger.info("⏸️ Sync is DISABLED (SYNC_ENABLED=0). Idle...")
            
            # Sleep 
            sleep_sec = int(os.getenv("SYNC_INTERVAL_SECONDS", "86400"))
            logger.info(f"💤 Sleeping for {sleep_sec} seconds...")
            await asyncio.sleep(sleep_sec)
    else:
        # Run once and exit (Cron/Manual Mode)
        # Always run if manually invoked, regardless of SYNC_ENABLED
        await run_sync_once()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
