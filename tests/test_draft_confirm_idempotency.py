import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.core.db import Base  # noqa: E402
from app.models.draft_db import NutritionDraftDB  # noqa: E402
from app.models.treatment import Treatment  # noqa: E402
from app.services.nutrition_draft_service import NutritionDraftService  # noqa: E402


class SyncAsyncSession:
    def __init__(self, sync_session):
        self._session = sync_session

    def add(self, obj):
        self._session.add(obj)

    async def commit(self):
        self._session.commit()

    async def execute(self, stmt, params=None):
        return self._session.execute(stmt, params or {})

    async def refresh(self, obj):
        self._session.refresh(obj)


@pytest_asyncio.fixture
async def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine, tables=[Treatment.__table__, NutritionDraftDB.__table__])
    Session = sessionmaker(bind=engine, future=True)
    sync_session = Session()
    try:
        yield SyncAsyncSession(sync_session)
    finally:
        sync_session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_draft_confirm_idempotent(db_session):
    draft, action = await NutritionDraftService.update_draft(
        "tester",
        new_c=42,
        new_f=10,
        new_p=7,
        new_fib=5,
        session=db_session,
    )
    assert action in {"created", "updated_replace", "updated_add"}

    treatment, created, draft_closed = await NutritionDraftService.close_draft_to_treatment(
        "tester",
        db_session,
        draft_id=draft.id,
    )
    assert treatment is not None
    assert created is True
    assert draft_closed is True

    db_session.add(treatment)
    await db_session.commit()

    treatment_retry, created_retry, draft_closed_retry = await NutritionDraftService.close_draft_to_treatment(
        "tester",
        db_session,
        draft_id=draft.id,
    )
    assert treatment_retry is not None
    assert treatment_retry.id == treatment.id
    assert created_retry is False
    assert draft_closed_retry is False

    saved = (await db_session.execute(select(Treatment))).scalars().all()
    assert len(saved) == 1
    assert saved[0].carbs == pytest.approx(42)
    assert saved[0].fat == pytest.approx(10)
    assert saved[0].protein == pytest.approx(7)
    assert saved[0].fiber == pytest.approx(5)
