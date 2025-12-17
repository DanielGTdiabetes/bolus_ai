import asyncio
import os
import sys
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential

# Add backend to pythonpath
backend_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_dir))

from app.models.basal import BasalEntry
from app.core.db import Base

# Setup logger
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("schema_updater")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def update_schema():
    print("Loading settings...")
    
    # Manually load env if present
    env_path = backend_dir.parent / ".env"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k,v = line.split("=", 1)
                    if k.strip() == "DATABASE_URL":
                        os.environ["DATABASE_URL"] = v.strip()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("No DATABASE_URL found")
        return

    # Fix postgres:// legacy
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://")
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    logger.info(f"Connecting to database: {db_url.split('@')[-1] if '@' in db_url else '...'}")
    
    try:
        engine = create_async_engine(db_url, echo=True)
        
        async with engine.begin() as conn:
            # 1. Create table if not exists (including new columns from definition)
            # SQLAlchemy create_all won't update existing tables, only create missing ones.
            # But we want to ensure table exists first.
            await conn.run_sync(Base.metadata.create_all)
            
            # 2. Manually ALTER table to add columns if they are missing
            # BasalEntry defines: basal_type, effective_hours, note
            
            logger.info("Checking for missing columns in basal_dose...")
            
            # Check basal_type
            try:
                await conn.execute(text("ALTER TABLE basal_dose ADD COLUMN IF NOT EXISTS basal_type VARCHAR"))
                logger.info("Added basal_type column")
            except Exception as e:
                logger.warning(f"Could not add basal_type: {e}")

            # Check effective_hours
            try:
                await conn.execute(text("ALTER TABLE basal_dose ADD COLUMN IF NOT EXISTS effective_hours INTEGER DEFAULT 24"))
                logger.info("Added effective_hours column")
            except Exception as e:
                logger.warning(f"Could not add effective_hours: {e}")
                
            # Check note
            try:
                await conn.execute(text("ALTER TABLE basal_dose ADD COLUMN IF NOT EXISTS note VARCHAR"))
                logger.info("Added note column")
            except Exception as e:
                logger.warning(f"Could not add note: {e}")
                
        logger.info("Schema update check completed.")
        
    except Exception as e:
        logger.error(f"Failed to connect or update: {e}")
        raise e
    finally:
        await engine.dispose()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(update_schema())
