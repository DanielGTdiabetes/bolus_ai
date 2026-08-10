import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.services.meal_session_service import (
    finish_meal_session,
    get_meal_session,
    record_bolus_in_session,
    record_carbs_added,
    start_meal_session,
    summarize_meal_session,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_meal_session_keeps_recorded_and_submitted_carbs_separate(db_session):
    meal = await start_meal_session(
        db_session,
        user_id="tester",
        meal_slot="dinner",
        label="Buffet",
        source="app",
    )

    first = await record_carbs_added(
        db_session,
        user_id="tester",
        session_id=meal.id,
        client_event_id="plate-0001",
        carbs_g=20,
        fat_g=5,
        protein_g=10,
    )
    duplicate = await record_carbs_added(
        db_session,
        user_id="tester",
        session_id=meal.id,
        client_event_id="plate-0001",
        carbs_g=20,
        fat_g=5,
        protein_g=10,
    )
    assert duplicate.id == first.id

    trace = {
        "snapshot": {
            "schema_version": 1,
            "source": "app",
            "recommended_u": 2.0,
            "accepted_u": 2.0,
            "meal_component_u": 2.0,
            "correction_component_u": 0.0,
            "iob_u": 3.5,
            "iob_applied_to_correction_u": 0.0,
        }
    }
    bolus = await record_bolus_in_session(
        db_session,
        user_id="tester",
        session_id=meal.id,
        treatment_id="treatment-0001",
        carbs_g=20,
        accepted_insulin_u=2.0,
        calculation_trace=trace,
    )
    duplicate_bolus = await record_bolus_in_session(
        db_session,
        user_id="tester",
        session_id=meal.id,
        treatment_id="treatment-0001",
        carbs_g=20,
        accepted_insulin_u=2.0,
        calculation_trace=trace,
    )
    assert duplicate_bolus.id == bolus.id

    loaded = await get_meal_session(db_session, user_id="tester", session_id=meal.id)
    summary = summarize_meal_session(loaded)
    assert summary["carbs_recorded_g"] == 20
    assert summary["carbs_submitted_for_bolus_g"] == 20
    assert summary["accepted_insulin_u"] == 2
    assert summary["event_count"] == 2

    bolus_event = next(event for event in summary["events"] if event["kind"] == "bolus_recorded")
    assert bolus_event["recommended_meal_u"] == 2.0
    assert bolus_event["recommended_correction_u"] == 0.0
    assert bolus_event["iob_u"] == 3.5
    assert bolus_event["iob_applied_to_correction_u"] == 0.0


@pytest.mark.asyncio
async def test_closed_meal_session_rejects_new_events(db_session):
    meal = await start_meal_session(db_session, user_id="tester", meal_slot="lunch")
    await finish_meal_session(
        db_session,
        user_id="tester",
        session_id=meal.id,
        status="closed",
    )

    with pytest.raises(ValueError, match="meal_session_not_active"):
        await record_carbs_added(
            db_session,
            user_id="tester",
            session_id=meal.id,
            client_event_id="plate-after-close",
            carbs_g=10,
        )


@pytest.mark.asyncio
async def test_start_is_idempotent_while_session_is_active(db_session):
    first = await start_meal_session(db_session, user_id="tester", meal_slot="breakfast")
    second = await start_meal_session(db_session, user_id="tester", meal_slot="dinner")
    assert second.id == first.id
    assert second.meal_slot == "breakfast"
