from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.db import Base, migrate_schema
from app.models.meal_learning import MealCluster, MealExperience
from app.models.settings import UserSettings
from app.models.treatment import Treatment
from app.services.meal_learning_service import (
    EVENT_KIND_CARBS_ONLY,
    EVENT_KIND_CORRECTION,
    EVENT_KIND_DUAL,
    EVENT_KIND_STANDARD,
    MealLearningService,
    build_cluster_key,
    classify_event_kind,
    should_use_learned_curve,
)
from app.services.nightscout_client import NightscoutSGV


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def async_session():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await migrate_schema(conn)

    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session

    await engine.dispose()


def test_classify_event_kind_variants():
    now = datetime.now(timezone.utc)
    correction = Treatment(
        id="t1",
        user_id="u1",
        event_type="Correction",
        created_at=now.replace(tzinfo=None),
        insulin=1.2,
        carbs=0.5,
        fat=0,
        protein=0,
        fiber=0,
        duration=0,
        notes=None,
        carb_profile=None,
        glucose=None,
        entered_by=None,
        is_uploaded=False,
        nightscout_id=None,
    )
    kind, _ = classify_event_kind(correction)
    assert kind == EVENT_KIND_CORRECTION

    carbs_only = Treatment(
        id="t2",
        user_id="u1",
        event_type="Meal Bolus",
        created_at=now.replace(tzinfo=None),
        insulin=0.05,
        carbs=20,
        fat=0,
        protein=0,
        fiber=0,
        duration=0,
        notes=None,
        carb_profile=None,
        glucose=None,
        entered_by=None,
        is_uploaded=False,
        nightscout_id=None,
    )
    kind, _ = classify_event_kind(carbs_only)
    assert kind == EVENT_KIND_CARBS_ONLY

    dual = Treatment(
        id="t3",
        user_id="u1",
        event_type="Meal Bolus",
        created_at=now.replace(tzinfo=None),
        insulin=6,
        carbs=60,
        fat=10,
        protein=10,
        fiber=2,
        duration=30,
        notes="dual",
        carb_profile=None,
        glucose=None,
        entered_by=None,
        is_uploaded=False,
        nightscout_id=None,
    )
    kind, _ = classify_event_kind(dual)
    assert kind == EVENT_KIND_DUAL

    standard = Treatment(
        id="t4",
        user_id="u1",
        event_type="Meal Bolus",
        created_at=now.replace(tzinfo=None),
        insulin=4,
        carbs=45,
        fat=5,
        protein=5,
        fiber=3,
        duration=0,
        notes=None,
        carb_profile=None,
        glucose=None,
        entered_by=None,
        is_uploaded=False,
        nightscout_id=None,
    )
    kind, _ = classify_event_kind(standard)
    assert kind == EVENT_KIND_STANDARD


@pytest.mark.asyncio
async def test_meal_learning_job_creates_experiences_and_clusters(async_session: AsyncSession):
    now = datetime.now(timezone.utc)
    created_at = (now - timedelta(hours=5)).replace(tzinfo=None)

    treatments = [
        Treatment(
            id="t1",
            user_id="u1",
            event_type="Meal Bolus",
            created_at=created_at,
            insulin=4,
            carbs=40,
            fat=8,
            protein=12,
            fiber=3,
            duration=0,
            notes=None,
            carb_profile="med",
            glucose=110,
            entered_by=None,
            is_uploaded=False,
            nightscout_id=None,
        ),
        Treatment(
            id="t2",
            user_id="u1",
            event_type="Correction",
            created_at=created_at,
            insulin=1.0,
            carbs=0.5,
            fat=0,
            protein=0,
            fiber=0,
            duration=0,
            notes=None,
            carb_profile=None,
            glucose=120,
            entered_by=None,
            is_uploaded=False,
            nightscout_id=None,
        ),
        Treatment(
            id="t3",
            user_id="u1",
            event_type="Meal Bolus",
            created_at=created_at,
            insulin=5,
            carbs=55,
            fat=20,
            protein=15,
            fiber=4,
            duration=20,
            notes="dual",
            carb_profile="slow",
            glucose=115,
            entered_by=None,
            is_uploaded=False,
            nightscout_id=None,
        ),
    ]
    async_session.add_all(treatments)
    await async_session.commit()

    def sgv_provider(treatment: Treatment, _window_minutes: int):
        start = treatment.created_at.replace(tzinfo=timezone.utc)
        return [
            NightscoutSGV(sgv=110, date=int(start.timestamp() * 1000), direction=None),
            NightscoutSGV(sgv=165, date=int((start + timedelta(hours=1)).timestamp() * 1000), direction=None),
            NightscoutSGV(sgv=130, date=int((start + timedelta(hours=3)).timestamp() * 1000), direction=None),
            NightscoutSGV(sgv=120, date=int((start + timedelta(hours=5)).timestamp() * 1000), direction=None),
        ]

    service = MealLearningService(async_session)
    created = await service.evaluate_treatments(
        user_id="u1",
        settings=UserSettings(),
        now=now,
        sgv_provider=sgv_provider,
    )
    assert created == 3

    experiences = (await async_session.execute(select(MealExperience))).scalars().all()
    assert len(experiences) == 3

    clusters = (await async_session.execute(select(MealCluster))).scalars().all()
    assert len(clusters) == 1
    assert clusters[0].n_ok == 1


def test_cluster_key_stable_for_similar_macros():
    key_a = build_cluster_key("med", "none", 42, 18, 12, 4, user_id="u1")
    key_b = build_cluster_key("med", "none", 49, 19, 19, 4, user_id="u1")
    assert key_a == key_b


def test_forecast_curve_gating():
    cluster = MealCluster(
        cluster_key="u1:med|none|C40-P10-F10-Fi0",
        user_id="u1",
        carb_profile="med",
        tags_key="none",
        n_ok=5,
        confidence="medium",
    )
    assert should_use_learned_curve(cluster) is True
    cluster.n_ok = 4
    assert should_use_learned_curve(cluster) is False


@pytest.mark.asyncio
async def test_migration_idempotent():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await migrate_schema(conn)
        await migrate_schema(conn)
    await engine.dispose()
