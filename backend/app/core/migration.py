
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
            else:
                # 2. Add column
                logger.warning("Column checkin_date MISSING in basal_checkin. Adding it...")
                try:
                    await conn.execute(text("ALTER TABLE basal_checkin ADD COLUMN checkin_date DATE;"))
                    await conn.commit()
                    logger.info("Column checkin_date added.")
                except Exception as e:
                    await conn.rollback()
                    logger.warning(f"Failed to add column checkin_date (might exist): {e}")
        except Exception as e:
            await conn.rollback()
            logger.warning(f"Error checking schema: {e}. Assuming we might need to fix.")

        # Ensure other columns: source, age_min
        logger.info("Checking source/age_min columns (Safe idempotency check)...")
        for col, type_ in [("source", "VARCHAR"), ("age_min", "INTEGER")]:
            try:
                # 1. Check if exists
                check_res = await conn.execute(text(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name='basal_checkin' AND column_name='{col}'"
                ))
                if check_res.fetchone():
                    logger.info(f"Column {col} already exists in basal_checkin.")
                else:
                    # 2. Add if missing
                    logger.info(f"Adding missing column {col}...")
                    await conn.execute(text(f"ALTER TABLE basal_checkin ADD COLUMN {col} {type_};"))
                    await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.warning(f"Error ensuring column {col}: {e}")


        # 3. Backfill
        logger.info("Backfilling checkin_date from created_at...")
        try:
            # If created_at exists, use it. Otherwise use current date.
            await conn.execute(text("UPDATE basal_checkin SET checkin_date = created_at::date WHERE checkin_date IS NULL AND created_at IS NOT NULL;"))
            await conn.execute(text("UPDATE basal_checkin SET checkin_date = CURRENT_DATE WHERE checkin_date IS NULL;"))
            await conn.commit()
            logger.info("Backfill complete.")
            
        except Exception as e:
            logger.error(f"Failed to backfill: {e}")

async def ensure_treatment_columns(engine: AsyncEngine):
    """
    Ensures that 'treatments' table has 'fiber', 'fat', 'protein' columns.
    Common issue when migrating from older usage.
    """
    if not engine:
        return

    logger.info("Checking treatments table schema...")
    
    async with engine.connect() as conn:
        columns_to_check = [
            ("fiber", "FLOAT DEFAULT 0"),
            ("fat", "FLOAT DEFAULT 0"),
            ("protein", "FLOAT DEFAULT 0"),
            ("notes", "TEXT"),
            ("is_uploaded", "BOOLEAN DEFAULT FALSE"),
            ("nightscout_id", "VARCHAR")
        ]
        
        for col_name, col_type in columns_to_check:
            try:
                # Check existance (Postgres)
                res = await conn.execute(text(
                    f"SELECT column_name FROM information_schema.columns WHERE table_name='treatments' AND column_name='{col_name}'"
                ))
                if not res.fetchone():
                    logger.warning(f"Column {col_name} missing in treatments. Adding...")
                    await conn.execute(text(f"ALTER TABLE treatments ADD COLUMN {col_name} {col_type};"))
                    await conn.commit()
                    
                    # Backfill nulls
                    if "DEFAULT" in col_type:
                        default_val = col_type.split("DEFAULT")[1].strip()
                        await conn.execute(text(f"UPDATE treatments SET {col_name} = {default_val} WHERE {col_name} IS NULL;"))
                        await conn.commit()
            except Exception as e:
                await conn.rollback()
                # Fallback for SQLite (no information_schema)
                # Just try adding it and ignore error
                try: 
                     await conn.execute(text(f"ALTER TABLE treatments ADD COLUMN {col_name} {col_type};"))
                     await conn.commit()
                except Exception:
                    await conn.rollback()
                    pass

        try:
            await conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_treatments_draft_id ON treatments (draft_id);")
            )
            await conn.commit()
        except Exception as e:
            await conn.rollback()
            logger.warning(f"Failed to ensure unique draft_id index: {e}")
