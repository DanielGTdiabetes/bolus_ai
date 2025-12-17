
import asyncio
import logging
import sys
from pathlib import Path
from sqlalchemy import text
from app.core.settings import get_settings
from app.core.db import get_engine, init_db

# Add backend to pythonpath
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.append(str(backend_dir))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_inspector")


# Load .env manually
import os
env_path = backend_dir.parent / ".env"
if env_path.exists():
    logger.info(f"Loading .env from {env_path}")
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

async def inspect():
    # Force init db to set up engine
    init_db()
    engine = get_engine()
    
    if not engine:
        logger.error("No DB engine initialized (check config/env)")
        return

    async with engine.connect() as conn:
        logger.info("--- LAST 5 BASAL DOSES ---")
        try:
            result = await conn.execute(text("SELECT * FROM basal_dose ORDER BY created_at DESC LIMIT 5"))
            rows = result.fetchall()
            if not rows:
                logger.info("No rows found in basal_dose.")
            for row in rows:
                logger.info(f"Row: {row}")
        except Exception as e:
            logger.error(f"Error querying basal_dose: {e}")

        logger.info("\n--- LAST 5 BASAL CHECKINS ---")
        try:
            result = await conn.execute(text("SELECT * FROM basal_checkin ORDER BY created_at DESC LIMIT 5"))
            rows = result.fetchall()
            for row in rows:
                logger.info(f"Row: {row}")
        except Exception as e:
            logger.error(f"Error querying basal_checkin: {e}")

if __name__ == "__main__":
    asyncio.run(inspect())
