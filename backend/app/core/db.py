import logging
import uuid
from typing import AsyncGenerator, Optional, List, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import text, select
from sqlalchemy.engine import make_url

from app.core.settings import get_settings

logger = logging.getLogger("uvicorn")

class Base(DeclarativeBase):
    pass

# Global engine/session factory
_async_engine = None
_async_session_factory = None
_in_memory_store = {
    "entries": [],
    "checkins": []
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
                max_overflow=20
            )
        else:
            _async_engine = create_async_engine(
                url, 
                echo=False, 
                pool_pre_ping=True,
                pool_size=20,
                max_overflow=20
            )

        _async_session_factory = async_sessionmaker(_async_engine, expire_on_commit=False)
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
            
        logger.warning("DATABASE_URL not set. Using in-memory (dict) storage. Data will be lost on restart.")

def get_engine():
    return _async_engine

async def check_db_health():
    """Simple health check: SELECT now()"""
    if not _async_engine:
        return {"ok": True, "mode": "memory", "message": "Running in in-memory mode. Data is volatile."}
    
    try:
        async with _async_engine.connect() as conn:
            result = await conn.execute(text("SELECT now()"))
            row = result.fetchone()
            return {
                "ok": True,
                "db_time": str(row[0]) if row else None,
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
            )
        """))

        # 8. injection_states
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS injection_states (
                user_id VARCHAR NOT NULL,
                plan VARCHAR NOT NULL,
                last_used_id VARCHAR NOT NULL,
                updated_at TIMESTAMP,
                PRIMARY KEY (user_id, plan)
            )
        """))

        
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
