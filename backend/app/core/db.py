import logging
import uuid
from typing import AsyncGenerator, Optional, List, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import text, select
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool, StaticPool

from app.core.settings import get_settings

logger = logging.getLogger("uvicorn")

class Base(DeclarativeBase):
    pass

# Global engine/session factory
_async_engine = None
_async_session_factory = None
_in_memory_store = {
    "entries": [],
    "checkins": [],
    "isf_runs": [],
}

def init_db():
    settings = get_settings()
    url = settings.database.url
    
    global _async_engine, _async_session_factory

    if url:
        # Sanitized log
        safe_url = url.split('@')[-1] if '@' in url else '...'
        logger.info(f"Connecting to database: {safe_url}")
        
        # Handle asyncpg sslmode/channel_binding issues
        if "asyncpg" in url:
            u = make_url(url)
            q = dict(u.query)
            connect_args = {}
            
            # Extract sslmode -> connect_args['ssl']
            if "sslmode" in q:
                mode = q.pop("sslmode")
                if mode == "require" or mode == "verify-full":
                    connect_args["ssl"] = "require"
                elif mode == "disable":
                    connect_args["ssl"] = False
                # defaulting to leaving it out if unknown, or passing it? 
                # asyncpg mostly wants 'require' or boolean.
            
            # Remove channel_binding (often unsupported kwarg for asyncpg via SA)
            if "channel_binding" in q:
                q.pop("channel_binding")
                
            u = u._replace(query=q)
            _async_engine = create_async_engine(
                u,
                connect_args=connect_args,
                echo=False,
                pool_pre_ping=True,
                pool_size=20,
                max_overflow=20,
            )
        else:
            engine_kwargs = {
                "echo": False,
                "pool_pre_ping": True,
            }
            if make_url(url).drivername.startswith("sqlite"):
                sqlite_url = make_url(url)
                query = dict(sqlite_url.query)
                database = sqlite_url.database or ""
                is_memory = (
                    database == ":memory:"
                    or ":memory:" in database
                    or query.get("mode") == "memory"
                )
                if is_memory:
                    engine_kwargs["poolclass"] = StaticPool
                    engine_kwargs["connect_args"] = {"check_same_thread": False}
                else:
                    engine_kwargs["poolclass"] = NullPool
            else:
                engine_kwargs["pool_size"] = 20
                engine_kwargs["max_overflow"] = 20
            _async_engine = create_async_engine(url, **engine_kwargs)

        _async_session_factory = async_sessionmaker(
            _async_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    else:
        # Safety Check for Production
        import os
        allow_in_memory = os.environ.get("BOLUS_AI_ALLOW_IN_MEMORY", "false").lower() == "true"
        
        if not allow_in_memory:
            msg = (
                "CRITICAL: DATABASE_URL is not set. Starting in In-Memory mode is DANGEROUS "
                "because IOB history will be lost on restart, leading to potential insulin stacking. "
                "To force in-memory mode (e.g. for testing), set env BOLUS_AI_ALLOW_IN_MEMORY=true."
            )
            logger.critical(msg)
            raise RuntimeError(msg)
            
        _async_engine = None
        _async_session_factory = None
        logger.warning("DATABASE_URL not set. Using in-memory (dict) storage. Data will be lost on restart.")

def get_engine():
    return _async_engine

def get_session_factory():
    return _async_session_factory

def SessionLocal():
    if not _async_session_factory:
        raise RuntimeError("Database not initialized")
    return _async_session_factory()

async def check_db_health():
    """Simple health check: SELECT now()"""
    if not _async_engine:
        return {"ok": True, "mode": "memory", "message": "Running in in-memory mode. Data is volatile."}
    
    try:
        async with _async_engine.connect() as conn:
            if _async_engine.url.drivername.startswith("sqlite"):
                result = await conn.execute(text("SELECT 1"))
                row = result.fetchone()
                db_time = None
            else:
                result = await conn.execute(text("SELECT now()"))
                row = result.fetchone()
                db_time = str(row[0]) if row else None
            return {
                "ok": True,
                "db_time": db_time,
                "database": "neondb", # Assumption/Hardcoded or derive
                "driver": _async_engine.driver
            }
    except Exception as e:
        logger.error(f"DB Health Check Failed: {e}")
        return {"ok": False, "error": str(e)}

async def migrate_schema(conn):
    """
    Apply any manual schema migrations that might be missing (e.g. new columns).
    This is a lightweight alternative to full Alembic for rapid agentic dev.
    """
    try:
        # 1. duration
        await conn.execute(text("ALTER TABLE treatments ADD COLUMN IF NOT EXISTS duration FLOAT DEFAULT 0.0"))
        
        # 2. fat
        await conn.execute(text("ALTER TABLE treatments ADD COLUMN IF NOT EXISTS fat FLOAT DEFAULT 0.0"))
        
        # 3. protein
        await conn.execute(text("ALTER TABLE treatments ADD COLUMN IF NOT EXISTS protein FLOAT DEFAULT 0.0"))
        
        # 4. fiber (treatments)
        await conn.execute(text("ALTER TABLE treatments ADD COLUMN IF NOT EXISTS fiber FLOAT DEFAULT 0.0"))

        # 4a. carb_profile (treatments)
        await conn.execute(text("ALTER TABLE treatments ADD COLUMN IF NOT EXISTS carb_profile VARCHAR"))

        # 4b. draft_id (treatments)
        await conn.execute(text("ALTER TABLE treatments ADD COLUMN IF NOT EXISTS draft_id VARCHAR"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_treatments_draft_id ON treatments (draft_id)"))

        # 5. fiber (favorite_foods)
        await conn.execute(text("ALTER TABLE favorite_foods ADD COLUMN IF NOT EXISTS fiber FLOAT DEFAULT 0.0"))
        
        # 6. fiber_g (meal_entries)
        await conn.execute(text("ALTER TABLE meal_entries ADD COLUMN IF NOT EXISTS fiber_g FLOAT DEFAULT 0.0"))

        # 7. supply_items (Ensure table exists if model sync failed)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS supply_items (
                id UUID PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                item_key VARCHAR NOT NULL,
                quantity INTEGER DEFAULT 0,
                updated_at TIMESTAMP,
                CONSTRAINT uq_user_supply_item UNIQUE (user_id, item_key)
            )
        """))

        # 8. injection_states
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS injection_states (
                user_id VARCHAR NOT NULL,
                plan VARCHAR NOT NULL,
                last_used_id VARCHAR NOT NULL,
                source VARCHAR NOT NULL DEFAULT 'auto',
                updated_at TIMESTAMP,
                PRIMARY KEY (user_id, plan)
            )
        """))
        # Ensure new columns exist on existing tables
        try:
            await conn.execute(text("ALTER TABLE injection_states ADD COLUMN IF NOT EXISTS source VARCHAR NOT NULL DEFAULT 'auto'"))
        except Exception as e:
            logger.warning(f"injection_states.source migration skipped or failed: {e}")
        try:
            await conn.execute(text("ALTER TABLE injection_states ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP"))
        except Exception as e:
            logger.warning(f"injection_states.updated_at migration skipped or failed: {e}")

        
        # 9. temp_modes
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS temp_modes (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                mode VARCHAR NOT NULL,
                started_at TIMESTAMP,
                expires_at TIMESTAMP,
                note TEXT
            )
        """))

        # 10. bot_leader_locks
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_leader_locks (
                key VARCHAR PRIMARY KEY,
                owner_id VARCHAR NOT NULL,
                acquired_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """))

        # 10. isf_runs
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS isf_runs (
                id UUID PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                timestamp TIMESTAMP,
                days INTEGER NOT NULL,
                n_events INTEGER NOT NULL,
                recommendation VARCHAR,
                diff_percent FLOAT,
                flags JSON
            )
        """))

        # 11. ml_training_data (LSTM/Transformer Dataset)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ml_training_data (
                feature_time TIMESTAMP NOT NULL,  -- 5 min bucketing
                user_id VARCHAR NOT NULL,
                sgv FLOAT,
                trend VARCHAR,
                iob FLOAT,
                cob FLOAT,
                basal_rate FLOAT,
                activity_score FLOAT,  -- Placeholder for steps/hr
                notes TEXT,
                PRIMARY KEY (feature_time, user_id)
            )
        """))
        
        # Ensure migration for existing tables that only have feature_time as PK
        try:
             await conn.execute(text("ALTER TABLE ml_training_data DROP CONSTRAINT IF EXISTS ml_training_data_pkey CASCADE"))
             await conn.execute(text("ALTER TABLE ml_training_data ADD PRIMARY KEY (feature_time, user_id)"))
        except Exception:
             pass

        # 12. ml_training_data_v2 (Extended ML Dataset)
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


        
        # Commit changes if using a connection that requires it (begin() usually handles this, but let's be safe)
        await conn.commit()
        await conn.commit()
        logger.info("✅ Database Migration: Columns checked/added to treatments and favorite_foods tables.")
    except Exception as e:
        logger.error(f"❌ Database Migration Error: {e}")
        # Don't raise, allow app to try and start, but the error will be in logs.

async def create_tables():
    if _async_engine:
        # We use a non-begin connection to have more control over commits if needed
        async with _async_engine.connect() as conn:
            # Create all (only creates new tables)
            await conn.run_sync(Base.metadata.create_all)
            # Apply column migrations
            await migrate_schema(conn)

# Abstraction for partial Repository pattern or Session usage
# To keep it compatible with Dependency Injection:

class InMemorySession:
    """Simulates an async session for our specific needs (add, commit, execute select)"""
    def __init__(self):
        self.store = _in_memory_store
        self._new_objects = []

    def add(self, obj):
        # We just track it, 'commit' effectively appends it
        self._new_objects.append(obj)

    async def commit(self):
        for obj in self._new_objects:
            # Determine collection based on type
            # This is a bit hacky but works for 'simple'
            name = obj.__tablename__
            if name in self.store:
                if not obj.id:
                    obj.id = uuid.uuid4()
                # If obj has created_at default, we might need to set it if None
                # SQLAlchemy does this effectively on DB side usually.
                # We'll handle it in the model instantiation or here.
                if hasattr(obj, 'created_at') and not obj.created_at:
                    obj.created_at = datetime.utcnow()
                
                self.store[name].append(obj)
        self._new_objects = []

    async def execute(self, statement):
        # Very limited support for 'select(Model).where(...).order_by(...)'
        # We will parse the statement manually or expects simple usage
        # This is the hard part of "dual mode". 
        # Alternatively, simpler: The Service handles the storage choice.
        pass

    async def refresh(self, obj):
        pass

# Better approach: return a DatabaseInterface, not a Session
# Or make endpoints handle the difference.
# Endpoints: "if db_session: use sql else: use dict"

async def get_db_session() -> AsyncGenerator[Any, None]:
    if _async_session_factory:
        async with _async_session_factory() as session:
            yield session
    else:
        yield None

from contextlib import asynccontextmanager

@asynccontextmanager
async def get_db_session_context():
    if not _async_session_factory:
        init_db()
    
    if _async_session_factory:
        async with _async_session_factory() as session:
            yield session
    else:
        # Fallback in-memory
        yield None
