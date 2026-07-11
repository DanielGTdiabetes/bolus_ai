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
        if (
            not self.conn.invalidated
            and not self.conn.closed
            and not self.conn.lock_active
            and not self.conn.transaction_aborted
        ):
            self.engine.reusable_connections.append(self.conn)
        return False


class FakeEngine:
    url = FakeUrl()

    def __init__(self, *connections):
        self.connections = list(connections)
        self.reusable_connections = []
        self.connect_count = 0

    def connect(self):
        conn = self.connections[self.connect_count]
        self.connect_count += 1
        return FakeConnectContext(self, conn)


class BaseFakeConnection:
    def __init__(
        self,
        *,
        release_error=None,
        init_error=None,
        rollback_error=None,
        best_effort_migration_aborts=False,
    ):
        self.release_error = release_error
        self.init_error = init_error
        self.rollback_error = rollback_error
        self.best_effort_migration_aborts = best_effort_migration_aborts
        self.executed = []
        self.invalidated = False
        self.invalidate_exc = None
        self.closed = False
        self.run_sync_calls = 0
        self.rollback_calls = 0
        self.migrate_calls = 0
        self.lock_active = False
        self.transaction_active = False
        self.transaction_aborted = False

    async def execute(self, statement):
        sql = str(statement)
        self.executed.append(sql)
        if "pg_advisory_lock" in sql and "unlock" not in sql:
            self.lock_active = True
            self.transaction_active = True
        elif "pg_advisory_unlock" in sql:
            if self.transaction_aborted:
                raise RuntimeError("current transaction is aborted")
            if self.release_error:
                raise self.release_error
            self.lock_active = False
            self.transaction_active = True
        else:
            self.transaction_active = True

    async def run_sync(self, fn):
        self.run_sync_calls += 1
        self.transaction_active = True
        if self.init_error:
            raise self.init_error

    def in_transaction(self):
        return self.transaction_active

    async def rollback(self):
        self.rollback_calls += 1
        if self.rollback_error:
            raise self.rollback_error
        self.transaction_active = False
        self.transaction_aborted = False

    async def close(self):
        self.closed = True


class FakeConnection(BaseFakeConnection):
    def invalidate(self, exc):
        self.invalidated = True
        self.invalidate_exc = exc


@pytest.fixture
def fast_create_tables(monkeypatch):
    monkeypatch.setattr(db, "DB_RETRY_ATTEMPTS", 1)

    async def fake_migrate(conn):
        conn.migrate_calls += 1
        conn.transaction_active = True
        if conn.best_effort_migration_aborts:
            # Simulate migrate_schema() catching and suppressing a DDL error after
            # PostgreSQL has marked the current transaction as aborted.
            conn.transaction_aborted = True
            return None
        conn.transaction_active = False

    monkeypatch.setattr(db, "migrate_schema", fake_migrate)


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
    assert conn.rollback_calls == 0
    assert not conn.lock_active
    assert not conn.invalidated
    assert engine.reusable_connections == [conn]


@pytest.mark.asyncio
async def test_best_effort_migration_abort_rolls_back_before_unlock(monkeypatch, fast_create_tables):
    conn = FakeConnection(best_effort_migration_aborts=True)
    engine = FakeEngine(conn)
    monkeypatch.setattr(db, "_async_engine", engine)

    await db.create_tables()

    unlock_index = next(i for i, sql in enumerate(conn.executed) if "pg_advisory_unlock" in sql)
    assert conn.rollback_calls == 1
    assert unlock_index >= 0
    assert not conn.transaction_aborted
    assert not conn.lock_active
    assert engine.reusable_connections == [conn]


@pytest.mark.asyncio
async def test_rollback_failure_invalidates_and_propagates_error(monkeypatch, fast_create_tables):
    rollback_error = RuntimeError("rollback failed")
    conn = FakeConnection(
        best_effort_migration_aborts=True,
        rollback_error=rollback_error,
    )
    engine = FakeEngine(conn)
    monkeypatch.setattr(db, "_async_engine", engine)

    with pytest.raises(RuntimeError, match="rollback failed"):
        await db.create_tables()

    assert conn.invalidated
    assert conn.invalidate_exc is rollback_error
    assert conn.lock_active
    assert conn.transaction_aborted
    assert engine.reusable_connections == []


@pytest.mark.asyncio
async def test_rollback_failure_closes_when_invalidate_unavailable(monkeypatch, fast_create_tables):
    conn = BaseFakeConnection(
        best_effort_migration_aborts=True,
        rollback_error=RuntimeError("rollback failed"),
    )
    engine = FakeEngine(conn)
    monkeypatch.setattr(db, "_async_engine", engine)

    with pytest.raises(RuntimeError, match="rollback failed"):
        await db.create_tables()

    assert conn.closed
    assert engine.reusable_connections == []


@pytest.mark.asyncio
async def test_unlock_failure_after_rollback_invalidates_and_propagates(monkeypatch, fast_create_tables):
    release_error = RuntimeError("unlock failed after rollback")
    conn = FakeConnection(
        best_effort_migration_aborts=True,
        release_error=release_error,
    )
    engine = FakeEngine(conn)
    monkeypatch.setattr(db, "_async_engine", engine)

    with pytest.raises(RuntimeError, match="unlock failed after rollback"):
        await db.create_tables()

    assert conn.rollback_calls == 1
    assert conn.invalidated
    assert conn.invalidate_exc is release_error
    assert conn.lock_active
    assert engine.reusable_connections == []


@pytest.mark.asyncio
async def test_create_tables_preserves_initialization_error_if_cleanup_also_fails(monkeypatch, fast_create_tables):
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


@pytest.mark.asyncio
async def test_second_startup_is_idempotent_after_clean_unlock(monkeypatch, fast_create_tables):
    first = FakeConnection(best_effort_migration_aborts=True)
    second = FakeConnection()
    engine = FakeEngine(first, second)
    monkeypatch.setattr(db, "_async_engine", engine)

    await db.create_tables()
    await db.create_tables()

    assert engine.connect_count == 2
    assert not first.lock_active
    assert not first.transaction_aborted
    assert not second.lock_active
    assert engine.reusable_connections == [first, second]
