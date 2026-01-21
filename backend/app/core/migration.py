
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




        # Fix Legacy 'day' column constraint if it exists (it might be NOT NULL)
        try:
            day_check = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='basal_checkin' AND column_name='day'"
            ))
            if day_check.fetchone():
                logger.info("Legacy column 'day' detected. Ensuring it is NULLABLE...")
                await conn.execute(text("ALTER TABLE basal_checkin ALTER COLUMN \"day\" DROP NOT NULL"))
                await conn.commit()
        except Exception as e:
            await conn.rollback()
            logger.warning(f"Error adjusting legacy day column: {e}")

        # Ensure Unique Index for ON CONFLICT support
        try:
            await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_basal_checkin_user_date ON basal_checkin (user_id, checkin_date);"))
            await conn.commit()
            logger.info("Unique index uq_basal_checkin_user_date verified.")
        except Exception as e:
            await conn.rollback()
            logger.warning(f"Failed to ensure unique index: {e}")

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

async def ensure_ml_schema(engine: AsyncEngine):
    """
    Ensures the ml_training_data table exists for the LSTM/Transformer model.
    Also handles schema migration for v2 table to ensure all columns exist.
    """
    if not engine:
        return

    logger.info("Checking ML training data schema...")
    async with engine.connect() as conn:
        try:
            # v1 table
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ml_training_data (
                    feature_time TIMESTAMP NOT NULL,
                    user_id VARCHAR NOT NULL,
                    sgv FLOAT,
                    trend VARCHAR,
                    iob FLOAT,
                    cob FLOAT,
                    basal_rate FLOAT,
                    activity_score FLOAT,
                    notes TEXT,
                    PRIMARY KEY (feature_time, user_id)
                )
            """))
            
            # v2 table - Core creation
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ml_training_data_v2 (
                    feature_time TIMESTAMP NOT NULL,
                    user_id VARCHAR NOT NULL,
                    bg_mgdl FLOAT,
                    trend VARCHAR,
                    bg_age_min FLOAT,
                    iob_u FLOAT,
                    cob_g FLOAT,
                    iob_status VARCHAR,
                    cob_status VARCHAR,
                    basal_active_u FLOAT,
                    basal_latest_u FLOAT,
                    basal_latest_age_min FLOAT,
                    basal_total_24h FLOAT,
                    basal_total_48h FLOAT,
                    bolus_total_3h FLOAT,
                    bolus_total_6h FLOAT,
                    carbs_total_3h FLOAT,
                    carbs_total_6h FLOAT,
                    exercise_minutes_6h FLOAT,
                    exercise_minutes_24h FLOAT,
                    baseline_bg_30m FLOAT,
                    baseline_bg_60m FLOAT,
                    baseline_bg_120m FLOAT,
                    baseline_bg_240m FLOAT,
                    baseline_bg_360m FLOAT,
                    active_params TEXT,
                    event_counts TEXT,
                    source_ns_enabled BOOLEAN,
                    source_ns_treatments_count INTEGER,
                    source_db_treatments_count INTEGER,
                    source_overlap_count INTEGER,
                    source_conflict_count INTEGER,
                    source_consistency_status VARCHAR,
                    flag_bg_missing BOOLEAN,
                    flag_bg_stale BOOLEAN,
                    flag_iob_unavailable BOOLEAN,
                    flag_cob_unavailable BOOLEAN,
                    flag_source_conflict BOOLEAN,
                    PRIMARY KEY (feature_time, user_id)
                )
            """))
            
            # v2 table - Column Verification & Backfill
            # This ensures that if the table existed with fewer columns, new ones are added.
            columns_v2 = [
                ("bg_mgdl", "FLOAT"),
                ("trend", "VARCHAR"),
                ("bg_age_min", "FLOAT"),
                ("iob_u", "FLOAT"),
                ("cob_g", "FLOAT"),
                ("iob_status", "VARCHAR"),
                ("cob_status", "VARCHAR"),
                ("basal_active_u", "FLOAT"),
                ("basal_latest_u", "FLOAT"),
                ("basal_latest_age_min", "FLOAT"),
                ("basal_total_24h", "FLOAT"),
                ("basal_total_48h", "FLOAT"),
                ("bolus_total_3h", "FLOAT"),
                ("bolus_total_6h", "FLOAT"),
                ("carbs_total_3h", "FLOAT"),
                ("carbs_total_6h", "FLOAT"),
                ("exercise_minutes_6h", "FLOAT"),
                ("exercise_minutes_24h", "FLOAT"),
                ("baseline_bg_30m", "FLOAT"),
                ("baseline_bg_60m", "FLOAT"),
                ("baseline_bg_120m", "FLOAT"),
                ("baseline_bg_240m", "FLOAT"),
                ("baseline_bg_360m", "FLOAT"),
                ("active_params", "TEXT"),
                ("event_counts", "TEXT"),
                ("source_ns_enabled", "BOOLEAN"),
                ("source_ns_treatments_count", "INTEGER"),
                ("source_db_treatments_count", "INTEGER"),
                ("source_overlap_count", "INTEGER"),
                ("source_conflict_count", "INTEGER"),
                ("source_consistency_status", "VARCHAR"),
                ("flag_bg_missing", "BOOLEAN"),
                ("flag_bg_stale", "BOOLEAN"),
                ("flag_iob_unavailable", "BOOLEAN"),
                ("flag_cob_unavailable", "BOOLEAN"),
                ("flag_source_conflict", "BOOLEAN"),
            ]

            logger.info("Verifying ml_training_data_v2 schema match...")
            data_cleanup_needed = False
            
            for col_name, col_type in columns_v2:
                try:
                    # Check if column exists
                    # Note: We use simpler check that works on most Postgres setups
                    # information_schema.columns is standard. 'ml_training_data_v2' is lowercased.
                    res = await conn.execute(text(
                        f"SELECT column_name FROM information_schema.columns "
                        f"WHERE table_name='ml_training_data_v2' AND column_name='{col_name}'"
                    ))
                    if not res.fetchone():
                        logger.warning(f"Column {col_name} missing in ml_training_data_v2. Adding it...")
                        await conn.execute(text(f"ALTER TABLE ml_training_data_v2 ADD COLUMN {col_name} {col_type}"))
                        data_cleanup_needed = True
                except Exception as e:
                    logger.warning(f"Schema check warning for {col_name}: {e}. Trying blind add...")
                    try:
                        await conn.execute(text(f"ALTER TABLE ml_training_data_v2 ADD COLUMN {col_name} {col_type}"))
                        data_cleanup_needed = True
                    except Exception:
                        pass # Likely exists or major error
            
            if data_cleanup_needed:
                logger.warning("Schema changes detected. Truncating invalid ML training data...")
                await conn.execute(text("TRUNCATE TABLE ml_training_data_v2"))
            else:
                # Secondary check: If columns existed but data is corrupt (NULLs in new critical fields)
                # This handles the case where users restarted between partial fixes.
                try:
                    # Check for rows with NULL in strict columns (e.g. basal_active_u should be float 0.0 or higher, never NULL if new code ran)
                    # We check a few key new columns.
                    bad_data_check = await conn.execute(text(
                        "SELECT COUNT(*) FROM ml_training_data_v2 WHERE basal_active_u IS NULL OR bg_age_min IS NULL"
                    ))
                    bad_count = bad_data_check.scalar()
                    if bad_count and bad_count > 0:
                        logger.warning(f"Found {bad_count} rows with corrupt/legacy data (NULLs). Truncating table to reset training...")
                        await conn.execute(text("TRUNCATE TABLE ml_training_data_v2"))
                except Exception as e:
                    logger.warning(f"Could not verify data integrity: {e}")

            await conn.commit()
            logger.info("✅ ML training data tables schema verified.")
        except Exception as e:
            await conn.rollback()
            logger.error(f"❌ Failed to ensure ML schema: {e}")
