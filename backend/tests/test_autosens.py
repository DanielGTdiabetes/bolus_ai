from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.db import Base
from app.models.autosens import AutosensRun
from app.models.settings import UserSettings
from app.services.autosens_service import AutosensService


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


class FakeSGV:
    def __init__(self, dt: datetime, sgv: float):
        self.date = int(dt.timestamp() * 1000)
        self.sgv = sgv


def make_sgvs(now: datetime, count: int, hypo_index: int | None = None) -> list[FakeSGV]:
    start = now - timedelta(minutes=5 * (count - 1))
    sgvs = []
    for i in range(count):
        dt = start + timedelta(minutes=5 * i)
        value = 65 if hypo_index is not None and i == hypo_index else 110
        sgvs.append(FakeSGV(dt, value))
    return sgvs


def make_ns_client(sgvs: list[FakeSGV]):
    class FakeNightscoutClient:
        def __init__(self, url: str, api_secret: str):
            self.url = url
            self.api_secret = api_secret

        async def get_sgv_range(self, start, end, count=2000):
            return sgvs

        async def aclose(self):
            return None

    return FakeNightscoutClient


@pytest.fixture
async def async_session():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session

    await engine.dispose()


def test_autosens_default_disabled():
    settings = UserSettings()
    assert settings.autosens.enabled is False


@pytest.mark.asyncio
async def test_autosens_run_logged(async_session, monkeypatch):
    from app.services import autosens_service as autosens_module

    now = datetime.now(timezone.utc)
    sgvs = make_sgvs(now, 20)
    monkeypatch.setattr(autosens_module, "NightscoutClient", make_ns_client(sgvs))
    async def fake_get_ns_config(session, username):
        return SimpleNamespace(enabled=True, url="http://ns", api_secret="secret")

    monkeypatch.setattr(autosens_module, "get_ns_config", fake_get_ns_config)

    settings = UserSettings()
    settings.autosens.enabled = True

    result = await AutosensService.calculate_autosens("user1", async_session, settings, record_run=True)
    assert result.ratio == 1.0

    stmt = select(AutosensRun).where(AutosensRun.user_id == "user1")
    row = (await async_session.execute(stmt)).scalars().first()
    assert row is not None
    assert row.enabled_state is True


@pytest.mark.asyncio
async def test_autosens_recent_hypos_guardrail(async_session, monkeypatch):
    from app.services import autosens_service as autosens_module

    now = datetime.now(timezone.utc)
    sgvs = make_sgvs(now, 12, hypo_index=10)
    monkeypatch.setattr(autosens_module, "NightscoutClient", make_ns_client(sgvs))
    async def fake_get_ns_config(session, username):
        return SimpleNamespace(enabled=True, url="http://ns", api_secret="secret")

    monkeypatch.setattr(autosens_module, "get_ns_config", fake_get_ns_config)

    settings = UserSettings()
    settings.autosens.enabled = True

    result = await AutosensService.calculate_autosens("user2", async_session, settings)
    assert result.ratio == 1.0
    assert "recent_hypos" in result.reason_flags


@pytest.mark.asyncio
async def test_autosens_insufficient_data_guardrail(async_session, monkeypatch):
    from app.services import autosens_service as autosens_module

    now = datetime.now(timezone.utc)
    sgvs = make_sgvs(now, 5)
    monkeypatch.setattr(autosens_module, "NightscoutClient", make_ns_client(sgvs))
    async def fake_get_ns_config(session, username):
        return SimpleNamespace(enabled=True, url="http://ns", api_secret="secret")

    monkeypatch.setattr(autosens_module, "get_ns_config", fake_get_ns_config)

    settings = UserSettings()
    settings.autosens.enabled = True

    result = await AutosensService.calculate_autosens("user3", async_session, settings)
    assert result.ratio == 1.0
    assert "insufficient_data" in result.reason_flags
