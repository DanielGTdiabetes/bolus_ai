from types import SimpleNamespace

import pytest

from app.core import db as db_module
from app.services import auth_repo


class _FakeConnection:
    def __init__(self):
        self.statements: list[str] = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement).strip())
        return None


class _FakeTransaction:
    def __init__(self, connection: _FakeConnection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeEngine:
    def __init__(self, drivername: str):
        self.url = SimpleNamespace(drivername=drivername)
        self.connection = _FakeConnection()

    def begin(self):
        return _FakeTransaction(self.connection)


@pytest.mark.asyncio
async def test_init_auth_db_sets_public_schema_before_creating_users(monkeypatch):
    engine = _FakeEngine("postgresql+asyncpg")
    monkeypatch.setattr(db_module, "_async_engine", engine)
    monkeypatch.setattr(auth_repo, "get_engine", lambda: engine)

    await auth_repo.init_auth_db()

    statements = engine.connection.statements
    assert statements[0] == "CREATE SCHEMA IF NOT EXISTS public"
    assert statements[1] == "SET LOCAL search_path TO public"
    assert statements[2].startswith("CREATE TABLE IF NOT EXISTS users")
    assert statements[3].startswith("INSERT INTO users")


@pytest.mark.asyncio
async def test_public_search_path_is_skipped_for_sqlite(monkeypatch):
    engine = _FakeEngine("sqlite+aiosqlite")
    monkeypatch.setattr(db_module, "_async_engine", engine)

    await db_module.set_postgres_public_search_path(
        engine.connection,
        ensure_schema=True,
    )

    assert engine.connection.statements == []
