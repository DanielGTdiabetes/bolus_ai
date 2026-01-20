from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.db import Base
from app.bot.leader_lock import try_acquire_bot_leader


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def async_session():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_bot_leader_lock_acquire_and_hold(async_session: AsyncSession):
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ok_first, info_first = await try_acquire_bot_leader(async_session, "inst-1", 60, now=now)
    assert ok_first is True
    assert info_first["action"] == "acquired"

    ok_second, info_second = await try_acquire_bot_leader(
        async_session,
        "inst-2",
        60,
        now=now + timedelta(seconds=5),
    )
    assert ok_second is False
    assert info_second["action"] == "held"

    ok_third, info_third = await try_acquire_bot_leader(
        async_session,
        "inst-1",
        60,
        now=now + timedelta(seconds=10),
    )
    assert ok_third is True
    assert info_third["action"] == "renewed"


@pytest.mark.asyncio
async def test_bot_leader_lock_expires_and_steals(async_session: AsyncSession):
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ok_first, info_first = await try_acquire_bot_leader(async_session, "inst-1", 30, now=now)
    assert ok_first is True
    assert info_first["action"] == "acquired"

    ok_second, info_second = await try_acquire_bot_leader(
        async_session,
        "inst-2",
        30,
        now=now + timedelta(seconds=31),
    )
    assert ok_second is True
    assert info_second["action"] == "stolen"
