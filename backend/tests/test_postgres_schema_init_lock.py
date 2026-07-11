import pytest

from app.core import db


class FakeUrl:
    drivername = "postgresql+asyncpg"


class FakeConnectContext:
    def __init__(self, engine, conn):
        self.engine = engine
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        if not self.conn.invalidated and not self.conn.closed:
            self.engine.reusable_connections.append(self.conn)
        return False


class FakeEngine:
    url = FakeUrl()

    def __init__(self, conn):
        self.conn = conn
        self.reusable_connections = []

    def connect(self):
        return FakeConnectContext(self, self.conn)


class BaseFakeConnection:
    def __init__(self, *, release_error=None, init_error=None):
        self.release_error = release_error
        self.init_error = init_error
        self.executed = []
        self.invalidated = False
        self.invalidate_exc = None
        self.closed = False
        self.run_sync_calls = 0

    async def execute(self, statement):
        sql = str(statement)
        self.executed.append(sql)
        if "pg_advisory_unlock" in sql and self.release_error:
            raise self.release_error

    async def run_sync(self, fn):
        self.run_sync_calls += 1
        if self.init_error:
            raise self.init_error

    async def close(self):
        self.closed = True


class FakeConnection(BaseFakeConnection):
    def invalidate(self, exc):
        self.invalidated = True
        self.invalidate_exc = exc


@pytest.fixture
def fast_create_tables(monkeypatch):
    monkeypatch.setattr(db, "DB_RETRY_ATTEMPTS", 1)

    async def noop_migrate(conn):
        return None

    monkeypatch.setattr(db, "migrate_schema", noop_migrate)


def test_release_postgres_schema_init_lock_executes_unlock():
    conn = FakeConnection()

    async def run():
        await db._release_postgres_schema_init_lock(conn)

    import asyncio
    asyncio.run(run())

    assert any("pg_advisory_unlock" in sql for sql in conn.executed)


@pytest.mark.asyncio
async def test_create_tables_releases_postgres_advisory_lock_on_success(monkeypatch, fast_create_tables):
    conn = FakeConnection()
    engine = FakeEngine(conn)
    monkeypatch.setattr(db, "_async_engine", engine)

    await db.create_tables()

    assert any("pg_advisory_lock" in sql for sql in conn.executed)
    assert any("pg_advisory_unlock" in sql for sql in conn.executed)
    assert not conn.invalidated
    assert engine.reusable_connections == [conn]


@pytest.mark.asyncio
async def test_create_tables_invalidates_connection_and_propagates_unlock_error(monkeypatch, fast_create_tables):
    release_error = RuntimeError("unlock failed")
    conn = FakeConnection(release_error=release_error)
    engine = FakeEngine(conn)
    monkeypatch.setattr(db, "_async_engine", engine)

    with pytest.raises(RuntimeError, match="unlock failed"):
        await db.create_tables()

    assert conn.invalidated
    assert conn.invalidate_exc is release_error
    assert engine.reusable_connections == []


@pytest.mark.asyncio
async def test_create_tables_closes_connection_when_invalidate_unavailable(monkeypatch, fast_create_tables):
    release_error = RuntimeError("unlock failed")
    conn = BaseFakeConnection(release_error=release_error)
    engine = FakeEngine(conn)
    monkeypatch.setattr(db, "_async_engine", engine)

    with pytest.raises(RuntimeError, match="unlock failed"):
        await db.create_tables()

    assert conn.closed
    assert engine.reusable_connections == []


@pytest.mark.asyncio
async def test_create_tables_preserves_initialization_error_if_unlock_also_fails(monkeypatch, fast_create_tables):
    init_error = ValueError("ddl failed")
    release_error = RuntimeError("unlock failed")
    conn = FakeConnection(init_error=init_error, release_error=release_error)
    engine = FakeEngine(conn)
    monkeypatch.setattr(db, "_async_engine", engine)

    with pytest.raises(ValueError, match="ddl failed"):
        await db.create_tables()

    assert conn.invalidated
    assert conn.invalidate_exc is release_error
    assert engine.reusable_connections == []
