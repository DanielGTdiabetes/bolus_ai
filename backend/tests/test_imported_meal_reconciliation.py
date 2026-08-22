from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - register all metadata
from app.core.db import Base
from app.services.imported_meal_service import (
    add_food,
    delete_food,
    discard_meal,
    edit_food,
    normalize_meal_type,
    reconcile_imported_meal,
    resolve_source_conflict,
)


@pytest.fixture
async def meal_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def candidate(
    meal: str,
    carbs: float,
    *,
    food_carbs: float | None = None,
    stable: bool = True,
    revision: str | None = None,
):
    return {
        "source": "MyFitnessPal-Hermes",
        "meal_id": f"hermes-mfp:2026-08-22:{meal}",
        "meal_revision": revision or f"{meal}-{carbs}",
        "date": "2026-08-22",
        "meal": meal,
        "source_carbs": carbs,
        "fat": 3,
        "protein": 8,
        "fiber": 2,
        "foods": [{"name": f"{meal} food", "quantity": "1", "unit": "unidad", "carbs_g": carbs if food_carbs is None else food_carbs}],
        "stability_confirmed": stable,
        "stable_read_count": 2 if stable else 1,
    }


@pytest.mark.asyncio
async def test_identical_meal_is_unchanged_and_not_notified_twice(meal_session):
    first = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p1")
    second = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p2")

    assert first.state == "NEW"
    assert first.should_notify is True
    assert second.meal.id == first.meal.id
    assert second.state == "UNCHANGED"
    assert second.should_notify is False
    assert second.meal.version == 1


@pytest.mark.asyncio
async def test_required_62_27_then_lunch_unchanged_and_only_dinner_new(meal_session):
    lunch_62 = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 62), sync_id="p1")
    lunch_27 = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p2")
    lunch_again = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p3")
    dinner = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("dinner", 31), sync_id="p3")

    assert lunch_62.state == "NEW"
    assert lunch_27.state == "UPDATED_UNTREATED"
    assert lunch_27.meal.id == lunch_62.meal.id
    assert lunch_again.state == "UNCHANGED"
    assert lunch_again.should_notify is False
    assert dinner.state == "NEW"
    assert dinner.should_notify is True
    assert dinner.meal.id != lunch_62.meal.id


@pytest.mark.asyncio
async def test_modified_after_bolus_is_updated_treated(meal_session):
    first = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p1")
    first.meal.treatment_status = "TREATED"
    first.meal.linked_bolus_id = "bolus-1"
    await meal_session.commit()

    changed = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 38), sync_id="p2")
    assert changed.state == "UPDATED_TREATED"
    assert changed.meal.id == first.meal.id
    assert changed.meal.linked_bolus_id == "bolus-1"


@pytest.mark.asyncio
async def test_source_total_mismatch_is_invalid_and_blocks_calculation(meal_session):
    result = await reconcile_imported_meal(
        meal_session,
        user_id="admin",
        payload=candidate("lunch", 62, food_carbs=27),
        sync_id="mismatch",
    )
    assert result.state == "INVALID"
    assert result.meal.validation_error == "carb_total_mismatch"
    assert result.meal.source_carbs == 62
    assert result.meal.calculated_carbs == 27


@pytest.mark.asyncio
async def test_unstable_62_27_27_only_accepts_last_stable_revision(meal_session):
    first = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 62, stable=False), sync_id="r1")
    second = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27, stable=False), sync_id="r2")
    third = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27, stable=False), sync_id="r3")

    assert first.should_notify is False
    assert second.should_notify is False
    assert third.state == "NEW"
    assert third.should_notify is True
    assert third.meal.is_stable is True
    assert third.meal.calculated_carbs == 27


@pytest.mark.asyncio
async def test_manual_food_edits_recalculate_version_and_fingerprint(meal_session):
    result = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p1")
    original_fingerprint = result.meal.fingerprint

    meal = await edit_food(meal_session, meal_id=result.meal.id, index=0, carbs=8)
    assert meal.calculated_carbs == 8
    assert meal.version == 2
    assert meal.fingerprint != original_fingerprint

    meal = await add_food(meal_session, meal_id=meal.id, name="Pan", carbs=4)
    assert meal.calculated_carbs == 12
    assert meal.version == 3

    meal = await delete_food(meal_session, meal_id=meal.id, index=0)
    assert meal.calculated_carbs == 4
    assert meal.version == 4
    assert [food["name"] for food in meal.foods] == ["Pan"]


@pytest.mark.asyncio
async def test_discarded_revision_does_not_reappear(meal_session):
    first = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p1")
    await discard_meal(meal_session, meal_id=first.meal.id)
    repeated = await reconcile_imported_meal(meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p2")

    assert repeated.state == "DISCARDED"
    assert repeated.should_notify is False


@pytest.mark.asyncio
async def test_each_distinct_source_conflict_after_manual_edit_gets_a_new_version(meal_session):
    first = await reconcile_imported_meal(
        meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p1"
    )
    manually_edited = await edit_food(
        meal_session, meal_id=first.meal.id, index=0, carbs=8
    )
    manual_version = manually_edited.version

    first_conflict = await reconcile_imported_meal(
        meal_session, user_id="admin", payload=candidate("lunch", 31), sync_id="p2"
    )
    first_conflict_version = first_conflict.meal.version
    second_conflict = await reconcile_imported_meal(
        meal_session, user_id="admin", payload=candidate("lunch", 35), sync_id="p3"
    )
    second_conflict_version = second_conflict.meal.version
    repeated_conflict = await reconcile_imported_meal(
        meal_session, user_id="admin", payload=candidate("lunch", 35), sync_id="p4"
    )

    assert first_conflict.should_notify is True
    assert first_conflict_version == manual_version + 1
    assert second_conflict.should_notify is True
    assert second_conflict_version == manual_version + 2
    assert repeated_conflict.should_notify is False
    assert repeated_conflict.meal.version == manual_version + 2


@pytest.mark.asyncio
async def test_spanish_meal_alias_is_persisted_as_canonical_slot(meal_session):
    result = await reconcile_imported_meal(
        meal_session, user_id="admin", payload=candidate("comida", 27), sync_id="alias"
    )

    assert result.meal.meal_type == "lunch"


def test_hermes_aperitivos_alias_uses_snack_slot():
    assert normalize_meal_type("aperitivos") == "snack"


@pytest.mark.asyncio
async def test_kept_manual_review_suppresses_same_rejected_source_revision(meal_session):
    first = await reconcile_imported_meal(
        meal_session, user_id="admin", payload=candidate("lunch", 27), sync_id="p1"
    )
    manually_edited = await edit_food(
        meal_session, meal_id=first.meal.id, index=0, carbs=8
    )
    conflict = await reconcile_imported_meal(
        meal_session, user_id="admin", payload=candidate("lunch", 31), sync_id="p2"
    )
    rejected_fingerprint = conflict.meal.pending_source_version["fingerprint"]
    kept = await resolve_source_conflict(
        meal_session, meal_id=manually_edited.id, use_source=False
    )
    kept_version = kept.version

    repeated = await reconcile_imported_meal(
        meal_session, user_id="admin", payload=candidate("lunch", 31), sync_id="p3"
    )
    repeated_pending = repeated.meal.pending_source_version
    changed = await reconcile_imported_meal(
        meal_session, user_id="admin", payload=candidate("lunch", 35), sync_id="p4"
    )

    assert kept.rejected_source_fingerprint == rejected_fingerprint
    assert repeated.should_notify is False
    assert repeated_pending is None
    assert changed.should_notify is True
    assert changed.meal.version == kept_version + 1
