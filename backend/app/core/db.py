import logging
import uuid
from typing import AsyncGenerator, Optional, List, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import text, select

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
        logger.info(f"Connecting to database: {url.split('@')[-1]}") # Log safe part
        _async_engine = create_async_engine(url, echo=False)
        _async_session_factory = async_sessionmaker(_async_engine, expire_on_commit=False)
    else:
        logger.warning("DATABASE_URL not set. Using in-memory (dict) storage. Data will be lost on restart.")

async def create_tables():
    if _async_engine:
        async with _async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

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
