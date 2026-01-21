from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.db import Base
from app.models.treatment import Treatment
from app.services import treatment_retrieval


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.mark.asyncio
async def test_get_recent_treatments_db_includes_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    async with SessionLocal() as session:
        session.add_all([
            Treatment(
                id="manual-1",
                user_id="admin",
                event_type="Meal Bolus",
                created_at=(now - timedelta(minutes=5)).replace(tzinfo=None),
                insulin=1.0,
                carbs=25.0,
                fat=0.0,
                protein=0.0,
                fiber=0.0,
                notes="Manual meal",
                entered_by="manual",
            ),
            Treatment(
                id="imported-1",
                user_id="admin",
                event_type="Meal Bolus",
                created_at=(now - timedelta(minutes=1)).replace(tzinfo=None),
                insulin=0.0,
                carbs=30.0,
                fat=2.0,
                protein=3.0,
                fiber=1.0,
                notes="Imported from Health: 2024-01-01 #imported",
                entered_by="webhook-integration",
            ),
        ])
        await session.commit()

    monkeypatch.setattr(treatment_retrieval, "get_engine", lambda: engine)

    treatments = await treatment_retrieval.get_recent_treatments_db(hours=1, username="admin")
    assert len(treatments) == 2
    assert treatments[0].enteredBy == "webhook-integration"
    assert {t.enteredBy for t in treatments} == {"manual", "webhook-integration"}

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_recent_treatments_db_includes_null_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime.now(timezone.utc).replace(microsecond=0)

    async with SessionLocal() as session:
        session.add_all([
            Treatment(
                id="legacy-1",
                user_id=None,
                event_type="Correction Bolus",
                created_at=(now - timedelta(minutes=3)).replace(tzinfo=None),
                insulin=1.0,
                carbs=0.0,
                fat=0.0,
                protein=0.0,
                fiber=0.0,
                notes="Legacy record",
                entered_by="legacy-client",
            ),
            Treatment(
                id="current-1",
                user_id="admin",
                event_type="Correction Bolus",
                created_at=(now - timedelta(minutes=2)).replace(tzinfo=None),
                insulin=0.5,
                carbs=0.0,
                fat=0.0,
                protein=0.0,
                fiber=0.0,
                notes="Current record",
                entered_by="modern-client",
            ),
        ])
        await session.commit()

    monkeypatch.setattr(treatment_retrieval, "get_engine", lambda: engine)

    treatments = await treatment_retrieval.get_recent_treatments_db(hours=1, username="admin")
    assert len(treatments) == 2
    assert {t.enteredBy for t in treatments} == {"legacy-client", "modern-client"}

    await engine.dispose()
