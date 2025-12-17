
import asyncio
import logging
import sys
from pathlib import Path

# Add backend to pythonpath so we can import app
# This assumes the script is located at backend/scripts/update_schema.py
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.append(str(backend_dir))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.settings import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("schema_updater")

async def update_schema():
    print(f"Loading settings...")
    try:
        settings = get_settings()
    except Exception as e:
        print(f"Error loading settings: {e}")
        return

    url = settings.database.url
    
    if not url:
        logger.error("No DATABASE_URL found in settings.")
        return

    # Sanitize URL for logging
    safe_url = url.split('@')[-1] if '@' in url else '...'
    logger.info(f"Connecting to database: {safe_url}")
    
    engine = create_async_engine(url)

    async with engine.begin() as conn:
        logger.info("Checking basal_dose table schema...")
        
        columns_to_add = [
            ("basal_type", "VARCHAR"),
            ("effective_hours", "INTEGER DEFAULT 24"),
            ("note", "VARCHAR"),
            ("effective_from", "DATE DEFAULT CURRENT_DATE")
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                logger.info(f"Attempting to add column {col_name}...")
                await conn.execute(text(f"ALTER TABLE basal_dose ADD COLUMN IF NOT EXISTS {col_name} {col_type};"))
                logger.info(f"Column {col_name} ensured.")
            except Exception as e:
                logger.warning(f"Could not add column {col_name} (might already exist or other error): {e}")

    await engine.dispose()
    logger.info("Schema update finished.")

if __name__ == "__main__":
    asyncio.run(update_schema())
