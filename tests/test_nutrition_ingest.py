import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.api.integrations import ingest_nutrition  # noqa: E402
from app.core.db import Base  # noqa: E402
from app.core.security import CurrentUser  # noqa: E402
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


@pytest.mark.asyncio
async def test_ingest_saves_fiber(db_session):
    ts = _ts_now()
    result = await ingest_nutrition(
        payload={"fiber": 12, "timestamp": ts},
        user=CurrentUser(username="tester", role="admin"),
        api_key=None,
        auth_header=None,
        session=db_session,
    )

    assert result["success"] is True
    saved = (await db_session.execute(select(Treatment))).scalars().all()
    assert len(saved) == 1
    assert saved[0].fiber == pytest.approx(12)


@pytest.mark.asyncio
async def test_ingest_updates_fiber_on_duplicate(db_session):
    ts = _ts_now()
    user = CurrentUser(username="tester", role="admin")

    await ingest_nutrition(
        payload={"fiber": 12, "timestamp": ts},
        user=user,
        api_key=None,
        auth_header=None,
        session=db_session,
    )
    await ingest_nutrition(
        payload={"fiber": 18, "timestamp": ts},
        user=user,
        api_key=None,
        auth_header=None,
        session=db_session,
    )

    saved = (await db_session.execute(select(Treatment))).scalars().all()
    assert len(saved) == 1
    assert saved[0].fiber == pytest.approx(18)


@pytest.mark.asyncio
async def test_ingest_accepts_fiber_only_entries(db_session):
    ts = _ts_now()
    result = await ingest_nutrition(
        payload={"carbs": 0, "fat": 0, "protein": 0, "fiber": 10, "timestamp": ts},
        user=CurrentUser(username="tester", role="admin"),
        api_key=None,
        auth_header=None,
        session=db_session,
    )

    assert result["success"] is True
    saved = (await db_session.execute(select(Treatment))).scalars().all()
    assert len(saved) == 1
    assert saved[0].carbs == pytest.approx(0)
    assert saved[0].fiber == pytest.approx(10)
