
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("uvicorn")

async def ensure_basal_schema(engine: AsyncEngine):
    """
    Checks if 'basal_checkin' table has 'checkin_date' column.
    If receiving UndefinedColumnError, it means it's missing.
    We add it and backfill.
    """
    if not engine:
        return

    logger.info("Checking basal_checkin schema...")
    
    async with engine.connect() as conn:
        # 1. Check if column exists
        # Postgres specific
        try:
            result = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='basal_checkin' AND column_name='checkin_date'"
            ))
            row = result.fetchone()
            if row:
                logger.info("Column checkin_date exists in basal_checkin. OK.")
                return
        except Exception as e:
            logger.warning(f"Error checking schema: {e}. Assuming we might need to fix.")

        # 2. Add column
        logger.warning("Column checkin_date MISSING in basal_checkin. Adding it...")
        try:
            await conn.execute(text("ALTER TABLE basal_checkin ADD COLUMN checkin_date DATE;"))
            await conn.commit()
            logger.info("Column checkin_date added.")
        except Exception as e:
            logger.warning(f"Failed to add column checkin_date (might exist): {e}")

        # Ensure other columns: source, age_min
        logger.info("Checking source/age_min columns...")
        for col, type_ in [("source", "VARCHAR"), ("age_min", "INTEGER")]:
            try:
                await conn.execute(text(f"ALTER TABLE basal_checkin ADD COLUMN {col} {type_};"))
                await conn.commit()
                logger.info(f"Column {col} added.")
            except Exception:
                pass # Assume exists


        # 3. Backfill
        logger.info("Backfilling checkin_date from created_at...")
        try:
            # If created_at exists, use it. Otherwise use current date.
            await conn.execute(text("UPDATE basal_checkin SET checkin_date = created_at::date WHERE checkin_date IS NULL AND created_at IS NOT NULL;"))
            await conn.execute(text("UPDATE basal_checkin SET checkin_date = CURRENT_DATE WHERE checkin_date IS NULL;"))
            await conn.commit()
            logger.info("Backfill complete.")
            
            # 4. Add constraint if possible?
            # Existing constraint might be on (user_id, created_at) or something else.
            # The model defines UniqueConstraint('user_id', 'checkin_date')
            # creating it properly involves dropping old unique constraints if they conflict, but let's safely skip that for hotfix.
            
        except Exception as e:
            logger.error(f"Failed to backfill: {e}")
