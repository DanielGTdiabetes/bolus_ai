import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import importlib.util
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.core.db import Base  # noqa: E402
from app.models.learning import MealEntry, MealOutcome, ShadowLog  # noqa: E402
from app.services.store import DataStore  # noqa: E402

analysis_path = ROOT_DIR / "backend" / "app" / "api" / "analysis.py"
spec = importlib.util.spec_from_file_location("analysis_module", analysis_path)
analysis_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis_module)
get_shadow_logs = analysis_module.get_shadow_logs


class SyncAsyncSession:
    def __init__(self, sync_session):
        self._session = sync_session

    def add(self, obj):
        self._session.add(obj)

    async def commit(self):
        self._session.commit()

    async def execute(self, stmt):
        return self._session.execute(stmt)


class SimpleUser:
    def __init__(self, username: str):
        self.username = username


@pytest_asyncio.fixture
async def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine, tables=[
        MealEntry.__table__,
        MealOutcome.__table__,
        ShadowLog.__table__,
    ])
    Session = sessionmaker(bind=engine, future=True)
    sync_session = Session()
    try:
        yield SyncAsyncSession(sync_session)
    finally:
        sync_session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_learning_history_in_shadow_logs(db_session, tmp_path):
    now = datetime.utcnow()

    entry_good = MealEntry(
        id=str(uuid4()),
        user_id="tester",
        created_at=now - timedelta(hours=6),
        items=["Pasta"],
        carbs_g=60,
    )
    outcome_good = MealOutcome(
        id=str(uuid4()),
        meal_entry_id=entry_good.id,
        evaluated_at=now - timedelta(hours=2),
        score=9,
        max_bg=165,
        min_bg=90,
        final_bg=120,
        hypo_occurred=False,
        hyper_occurred=False,
    )

    entry_bad = MealEntry(
        id=str(uuid4()),
        user_id="tester",
        created_at=now - timedelta(hours=10),
        items=["Pizza"],
        carbs_g=80,
    )
    outcome_bad = MealOutcome(
        id=str(uuid4()),
        meal_entry_id=entry_bad.id,
        evaluated_at=now - timedelta(hours=5),
        score=4,
        max_bg=280,
        min_bg=110,
        final_bg=240,
        hypo_occurred=False,
        hyper_occurred=True,
    )

    db_session.add(entry_good)
    db_session.add(outcome_good)
    db_session.add(entry_bad)
    db_session.add(outcome_bad)
    await db_session.commit()

    store = DataStore(tmp_path)
    user = SimpleUser("tester")

    logs = await get_shadow_logs(limit=10, current_user=user, store=store, db=db_session)

    assert len(logs) == 2
    assert logs[0]["meal_name"] == "Pasta"
    assert logs[0]["status"] == "success"
    assert logs[1]["meal_name"] == "Pizza"
    assert logs[1]["status"] == "failed"
