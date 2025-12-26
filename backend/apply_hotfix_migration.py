
import asyncio
import logging
from app.core.db import init_db, get_engine
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_schema():
    logger.info("Initializing DB connection...")
    init_db()
    engine = get_engine()
    if not engine:
        logger.error("Engine not initialized. Check DATABASE_URL.")
        return

    logger.info("Applying migrations for treatments table...")
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE treatments ADD COLUMN IF NOT EXISTS fat FLOAT DEFAULT 0.0;"))
            await conn.execute(text("ALTER TABLE treatments ADD COLUMN IF NOT EXISTS protein FLOAT DEFAULT 0.0;"))
            logger.info("✅ Migration successful: 'fat' and 'protein' columns added.")
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(fix_schema())
