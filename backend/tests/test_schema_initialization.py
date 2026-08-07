import asyncio

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 - register all SQLAlchemy models
from app.core import db as core_db
from app.models.nutrition_event_identity import NutritionEventIdentity


@pytest.fixture()
def isolated_sqlite_engine(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'schema_init.db'}",
        poolclass=NullPool,
        echo=False,
    )
    monkeypatch.setattr(core_db, "_async_engine", engine)
    yield engine
    asyncio.get_event_loop().run_until_complete(engine.dispose())


async def _nutrition_columns(engine):
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda sync_conn: {
                col["name"]: str(col["type"])
                for col in inspect(sync_conn).get_columns("nutrition_event_identities")
            }
        )


@pytest.mark.asyncio
async def test_empty_sqlite_database_initializes_schema(isolated_sqlite_engine):
    await core_db.create_tables()

    async with isolated_sqlite_engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))

    assert "nutrition_event_identities" in table_names
    columns = await _nutrition_columns(isolated_sqlite_engine)
    assert set(columns) == {column.name for column in NutritionEventIdentity.__table__.columns}


@pytest.mark.asyncio
async def test_existing_nutrition_identity_table_starts_without_destructive_recreate(isolated_sqlite_engine):
    async with isolated_sqlite_engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE nutrition_event_identities (
                identity_key VARCHAR(64) NOT NULL PRIMARY KEY,
                treatment_id VARCHAR NOT NULL,
                user_id VARCHAR NOT NULL,
                source VARCHAR(32) NOT NULL,
                external_id_hash VARCHAR(64) NOT NULL,
                food_fingerprint VARCHAR(64),
                match_strategy VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL
            )
        """))
        await conn.execute(text("""
            INSERT INTO nutrition_event_identities (
                identity_key, treatment_id, user_id, source, external_id_hash,
                food_fingerprint, match_strategy, created_at
            ) VALUES ('existing-key', 'treatment-1', 'user-1', 'health_connect', 'hash-1', NULL, 'external_id', '2026-07-11 00:00:00')
        """))

    before_columns = await _nutrition_columns(isolated_sqlite_engine)
    await core_db.create_tables()
    after_columns = await _nutrition_columns(isolated_sqlite_engine)

    async with isolated_sqlite_engine.connect() as conn:
        row_count = (await conn.execute(text("SELECT COUNT(*) FROM nutrition_event_identities"))).scalar_one()

    assert row_count == 1
    assert after_columns == before_columns


@pytest.mark.asyncio
async def test_two_concurrent_sqlite_initializations_are_safe(isolated_sqlite_engine):
    await asyncio.gather(core_db.create_tables(), core_db.create_tables())

    columns = await _nutrition_columns(isolated_sqlite_engine)
    assert set(columns) == {column.name for column in NutritionEventIdentity.__table__.columns}


@pytest.mark.asyncio
async def test_second_schema_initialization_is_idempotent(isolated_sqlite_engine):
    await core_db.create_tables()
    before_columns = await _nutrition_columns(isolated_sqlite_engine)

    await core_db.create_tables()
    after_columns = await _nutrition_columns(isolated_sqlite_engine)

    assert after_columns == before_columns


class _FakePostgresConnection:
    def __init__(self, lock: asyncio.Lock, events: list[str]):
        self._lock = lock
        self._events = events

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "pg_advisory_lock" in sql and "unlock" not in sql:
            self._events.append("wait_lock")
            await self._lock.acquire()
            self._events.append("lock")
        elif "pg_advisory_unlock" in sql:
            self._events.append("unlock")
            self._lock.release()
        return None

    async def run_sync(self, fn):
        self._events.append("ddl_start")
        assert self._lock.locked(), "DDL must run only while the advisory lock is held"
        await asyncio.sleep(0.01)
        self._events.append("ddl_end")

    async def rollback(self):
        self._events.append("rollback")

    async def commit(self):
        self._events.append("commit")


class _FakeConnectContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePostgresEngine:
    url = make_url("postgresql+asyncpg://user:pass@example.com/db")

    def __init__(self):
        self._lock = asyncio.Lock()
        self.events: list[str] = []

    def connect(self):
        return _FakeConnectContext(_FakePostgresConnection(self._lock, self.events))


@pytest.mark.asyncio
async def test_postgres_schema_initialization_uses_advisory_lock_for_concurrent_starts(monkeypatch):
    engine = _FakePostgresEngine()
    monkeypatch.setattr(core_db, "_async_engine", engine)

    async def fake_migrate_schema(conn):
        engine.events.append("migrate")

    monkeypatch.setattr(core_db, "migrate_schema", fake_migrate_schema)

    await asyncio.gather(core_db.create_tables(), core_db.create_tables())

    assert engine.events.count("lock") == 2
    assert engine.events.count("unlock") == 2
    first_unlock = engine.events.index("unlock")
    assert "ddl_start" in engine.events[:first_unlock]
    assert engine.events[first_unlock + 1:].count("ddl_start") == 1
