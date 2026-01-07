import importlib.util
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "backend"))

from app.core.db import Base  # noqa: E402
from app.models.treatment import Treatment  # noqa: E402
from app.services.treatment_logger import log_treatment  # noqa: E402
from app.services.store import DataStore  # noqa: E402

nightscout_path = ROOT_DIR / "backend" / "app" / "api" / "nightscout.py"
nightscout_spec = importlib.util.spec_from_file_location("nightscout_api", nightscout_path)
nightscout_api = importlib.util.module_from_spec(nightscout_spec)
nightscout_spec.loader.exec_module(nightscout_api)


class SyncAsyncSession:
    def __init__(self, sync_session):
        self._session = sync_session

    def add(self, obj):
        self._session.add(obj)

    async def commit(self):
        self._session.commit()

    async def execute(self, stmt, params=None):
        return self._session.execute(stmt, params or {})

    async def delete(self, obj):
        self._session.delete(obj)


class FakeNightscoutClient:
    def __init__(self, *args, **kwargs):
        self.deleted_ids = []

    async def upload_treatments(self, treatments):
        return [{"_id": "ns-123"}]

    async def delete_treatment(self, treatment_id):
        self.deleted_ids.append(treatment_id)

    async def aclose(self):
        return None


class FakeNsConfig:
    def __init__(self):
        self.enabled = True
        self.url = "http://nightscout.example"
        self.api_secret = "token"


async def fake_get_ns_config(*args, **kwargs):
    return FakeNsConfig()


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
async def test_log_treatment_stores_nightscout_id(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.treatment_logger.NightscoutClient",
        FakeNightscoutClient,
    )

    result = await log_treatment(
        "tester",
        carbs=12,
        insulin=1.5,
        ns_url="http://nightscout.example",
        ns_token="token",
        session=db_session,
    )
    assert result.ok

    saved = (await db_session.execute(select(Treatment))).scalars().all()
    assert len(saved) == 1
    assert saved[0].nightscout_id == "ns-123"


@pytest.mark.asyncio
async def test_delete_uses_nightscout_id(db_session, monkeypatch, tmp_path):
    fake_client = FakeNightscoutClient()

    monkeypatch.setattr(
        nightscout_api,
        "NightscoutClient",
        lambda *args, **kwargs: fake_client,
    )
    monkeypatch.setattr(
        nightscout_api,
        "get_ns_config",
        fake_get_ns_config,
    )

    treatment = Treatment(
        id="local-uuid",
        user_id="tester",
        event_type="Meal Bolus",
        created_at=datetime(2024, 1, 1),
        insulin=0.0,
        carbs=30.0,
        fat=0.0,
        protein=0.0,
        fiber=0.0,
        notes="",
        entered_by="tester",
        is_uploaded=False,
        nightscout_id="ns-abc",
    )
    db_session.add(treatment)
    await db_session.commit()

    await nightscout_api.delete_treatment(
        "local-uuid",
        user=SimpleNamespace(username="tester"),
        session=db_session,
        store=DataStore(tmp_path),
    )

    assert fake_client.deleted_ids == ["ns-abc"]


@pytest.mark.asyncio
async def test_delete_warns_when_missing_nightscout_id(db_session, monkeypatch, tmp_path, caplog):
    fake_client = FakeNightscoutClient()

    monkeypatch.setattr(
        nightscout_api,
        "NightscoutClient",
        lambda *args, **kwargs: fake_client,
    )
    monkeypatch.setattr(
        nightscout_api,
        "get_ns_config",
        fake_get_ns_config,
    )

    treatment = Treatment(
        id="local-uuid",
        user_id="tester",
        event_type="Meal Bolus",
        created_at=datetime(2024, 1, 1),
        insulin=0.0,
        carbs=25.0,
        fat=0.0,
        protein=0.0,
        fiber=0.0,
        notes="",
        entered_by="tester",
        is_uploaded=False,
        nightscout_id=None,
    )
    db_session.add(treatment)
    await db_session.commit()

    caplog.set_level(logging.WARNING)

    await nightscout_api.delete_treatment(
        "local-uuid",
        user=SimpleNamespace(username="tester"),
        session=db_session,
        store=DataStore(tmp_path),
    )

    assert not fake_client.deleted_ids
    assert "Skipping NS delete" in caplog.text
