import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.api.integrations import ingest_nutrition  # noqa: E402
from app.core.db import Base  # noqa: E402
from app.core.security import TokenManager  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
from app.models.treatment import Treatment  # noqa: E402


def _ts_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SyncAsyncSession:
    def __init__(self, sync_session):
        self._session = sync_session

    def add(self, obj):
        self._session.add(obj)

    async def commit(self):
        self._session.commit()

    async def execute(self, stmt):
        return self._session.execute(stmt)

    async def get(self, model, pk):
        return self._session.get(model, pk)


@pytest_asyncio.fixture
async def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine, tables=[Treatment.__table__])
    Session = sessionmaker(bind=engine, future=True)
    sync_session = Session()
    try:
        yield SyncAsyncSession(sync_session)
    finally:
        sync_session.close()
        engine.dispose()


@pytest.fixture
def nutrition_key(monkeypatch):
    key = "secret-key"
    monkeypatch.setenv("NUTRITION_INGEST_KEY", key)
    monkeypatch.setenv("NUTRITION_INGEST_SECRET", key)
    get_settings.cache_clear()
    return key


@pytest.fixture
def settings(nutrition_key):
    return get_settings()


@pytest.fixture
def token_manager(settings):
    return TokenManager(settings)


def _make_request(query: str = ""):
    async def _receive():
        return {"type": "http.request"}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/integrations/nutrition",
        "raw_path": b"/api/integrations/nutrition",
        "query_string": query.encode(),
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
    }
    return Request(scope, receive=_receive)


@pytest.mark.asyncio
async def test_ingest_saves_fiber(db_session, token_manager, nutrition_key, settings):
    ts = _ts_now()
    result = await ingest_nutrition(
        payload={"fiber": 12, "timestamp": ts},
        request=_make_request(f"key={nutrition_key}"),
        authorization=None,
        ingest_key_header=None,
        session=db_session,
        token_manager=token_manager,
        settings=settings,
    )

    assert result["success"] == 1
    saved = (await db_session.execute(select(Treatment))).scalars().all()
    assert len(saved) == 1
    assert saved[0].fiber == pytest.approx(12)


@pytest.mark.asyncio
async def test_ingest_updates_fiber_on_duplicate(db_session, token_manager, nutrition_key, settings):
    ts = _ts_now()

    await ingest_nutrition(
        payload={"fiber": 12, "timestamp": ts},
        request=_make_request(f"key={nutrition_key}"),
        authorization=None,
        ingest_key_header=None,
        session=db_session,
        token_manager=token_manager,
        settings=settings,
    )
    await ingest_nutrition(
        payload={"fiber": 18, "timestamp": ts},
        request=_make_request(f"key={nutrition_key}"),
        authorization=None,
        ingest_key_header=None,
        session=db_session,
        token_manager=token_manager,
        settings=settings,
    )

    saved = (await db_session.execute(select(Treatment))).scalars().all()
    assert len(saved) == 1
    assert saved[0].fiber == pytest.approx(18)


@pytest.mark.asyncio
async def test_ingest_accepts_fiber_only_entries(db_session, token_manager, nutrition_key, settings):
    ts = _ts_now()
    result = await ingest_nutrition(
        payload={"carbs": 0, "fat": 0, "protein": 0, "fiber": 10, "timestamp": ts},
        request=_make_request(f"key={nutrition_key}"),
        authorization=None,
        ingest_key_header=None,
        session=db_session,
        token_manager=token_manager,
        settings=settings,
    )

    assert result["success"] == 1
    saved = (await db_session.execute(select(Treatment))).scalars().all()
    assert len(saved) == 1
    assert saved[0].carbs == pytest.approx(0)
    assert saved[0].fiber == pytest.approx(10)


@pytest.mark.asyncio
async def test_ingest_rejects_without_auth(db_session, token_manager, monkeypatch, settings):
    monkeypatch.delenv("NUTRITION_INGEST_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        await ingest_nutrition(
            payload={"fiber": 5},
            request=_make_request(),
            authorization=None,
            ingest_key_header=None,
            session=db_session,
            token_manager=token_manager,
            settings=settings,
        )

    assert exc.value.status_code == 401
    assert exc.value.detail["success"] == 0


@pytest.mark.asyncio
async def test_ingest_accepts_bearer_token(db_session, token_manager, settings):
    ts = _ts_now()
    token = token_manager.create_access_token("tester")

    result = await ingest_nutrition(
        payload={"fiber": 7, "timestamp": ts},
        request=_make_request(),
        authorization=f"Bearer {token}",
        ingest_key_header=None,
        session=db_session,
        token_manager=token_manager,
        settings=settings,
    )

    assert result["success"] == 1
    saved = (await db_session.execute(select(Treatment))).scalars().all()
    assert len(saved) == 1
    assert saved[0].fiber == pytest.approx(7)
