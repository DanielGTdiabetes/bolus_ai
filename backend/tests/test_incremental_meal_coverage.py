from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.bolus_v2 import BolusRequestV2, GlucoseUsed
from app.models.meal_coverage import MealCoverageState
from app.models.settings import UserSettings
from app.services.bolus_engine import calculate_bolus_v2
from app.services.meal_coverage_service import (
    calculate_incremental_nutrition,
    covered_after_confirmation,
    finalize_confirmation,
    get_meal_state,
    nutrition_revision,
    reserve_confirmation,
    state_context,
    upsert_current_meal,
    validate_confirmation_for_treatment,
)


MEAL_ID = "myfitnesspal|meal-2026-08-14-lunch"
USER_ID = "coverage-user"


@pytest.fixture()
async def coverage_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'coverage.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[MealCoverageState.__table__]
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _import(factory, nutrition):
    revision = nutrition_revision(nutrition)
    async with factory() as session:
        result = await upsert_current_meal(
            session,
            user_id=USER_ID,
            external_meal_id=MEAL_ID,
            source="MyFitnessPal",
            revision=revision,
            nutrition=nutrition,
        )
        await session.commit()
        return state_context(result.state)


async def _confirm(factory, context, calculation_id, bolus=8.0):
    async with factory() as session:
        reservation = await reserve_confirmation(
            session,
            user_id=USER_ID,
            external_meal_id=MEAL_ID,
            expected_revision=context["revision"],
            expected_covered=context["covered"],
            calculation_id=calculation_id,
        )
    assert reservation.ok
    covered_after, fraction, _, _ = covered_after_confirmation(
        covered_before=context["covered"],
        delta=context["delta"],
        accepted_u=bolus,
        recommended_upfront_u=bolus,
        positive_correction_after_iob_u=0,
        round_step_u=0.1,
    )
    assert fraction == 1
    async with factory() as session:
        result = await finalize_confirmation(
            session,
            user_id=USER_ID,
            external_meal_id=MEAL_ID,
            calculation_id=calculation_id,
            treatment_id=f"treatment-{calculation_id}",
            covered_after=covered_after,
            confirmed_bolus=bolus,
            confirmed_at=datetime.now(timezone.utc),
        )
    assert result.ok
    return result.context


def _calculate(
    carbs, *, fat=0.0, protein=0.0, autosens=1.0, iob=0.0, bg=None, warsaw=False
):
    settings = UserSettings()
    settings.cr.lunch = 9.0
    settings.cf.lunch = 30.0
    settings.targets.lunch = 100.0
    settings.max_iob_u = 30.0
    settings.warsaw.enabled = warsaw
    request = BolusRequestV2(
        carbs_g=carbs,
        fat_g=fat,
        protein_g=protein,
        meal_slot="lunch",
        bg_mgdl=bg,
    )
    return calculate_bolus_v2(
        request,
        settings,
        iob_u=iob,
        glucose_info=GlucoseUsed(
            mgdl=bg, source="manual" if bg is not None else "none"
        ),
        autosens_ratio=autosens,
    )


def test_case_1_new_meal_calculates_all_nutrition():
    result = calculate_incremental_nutrition(
        {"carbs": 63, "fat": 10, "protein": 20, "fiber": 4}, None
    )
    assert result.delta == {"carbs": 63.0, "fat": 10.0, "protein": 20.0, "fiber": 4.0}


@pytest.mark.asyncio
async def test_case_2_added_carbs_and_macros_after_confirmed_bolus_are_incremental(coverage_db):
    first = await _import(coverage_db, {"carbs": 63, "fat": 10, "protein": 20, "fiber": 4})
    await _confirm(coverage_db, first, "calc-1")
    updated = await _import(coverage_db, {"carbs": 87, "fat": 15, "protein": 25, "fiber": 5})
    assert updated["delta"] == {"carbs": 24.0, "fat": 5.0, "protein": 5.0, "fiber": 1.0}
    incremental_warsaw = _calculate(24, fat=5, protein=5, warsaw=True)
    incorrect_full_warsaw = _calculate(87, fat=15, protein=25, warsaw=True)
    assert incremental_warsaw.meal_bolus_u < incorrect_full_warsaw.meal_bolus_u
    assert any("Warsaw" in line for line in incremental_warsaw.explain)


@pytest.mark.asyncio
async def test_case_3_unchanged_confirmed_meal_has_zero_food_delta(coverage_db):
    first = await _import(coverage_db, {"carbs": 63})
    await _confirm(coverage_db, first, "calc-unchanged")
    repeated = await _import(coverage_db, {"carbs": 63})
    assert repeated["delta"]["carbs"] == 0


@pytest.mark.asyncio
async def test_case_4_unconfirmed_recommendation_covers_nothing(coverage_db):
    await _import(coverage_db, {"carbs": 63})
    updated = await _import(coverage_db, {"carbs": 87})
    assert updated["covered"]["carbs"] == 0
    assert updated["delta"]["carbs"] == 87


@pytest.mark.asyncio
async def test_case_5_reduced_meal_never_creates_negative_insulin_delta(coverage_db):
    first = await _import(coverage_db, {"carbs": 80})
    await _confirm(coverage_db, first, "calc-reduced")
    reduced = await _import(coverage_db, {"carbs": 60})
    assert reduced["delta"]["carbs"] == 0
    assert reduced["reductions"]["carbs"] == 20


@pytest.mark.asyncio
async def test_case_6_two_successive_extensions_only_cover_the_last_delta(coverage_db):
    first = await _import(coverage_db, {"carbs": 63})
    await _confirm(coverage_db, first, "calc-a")
    second = await _import(coverage_db, {"carbs": 87})
    assert second["delta"]["carbs"] == 24
    await _confirm(coverage_db, second, "calc-b", bolus=3.2)
    third = await _import(coverage_db, {"carbs": 100})
    assert third["covered"]["carbs"] == 87
    assert third["delta"]["carbs"] == 13


def test_case_7_current_autosens_applies_only_to_new_carbs():
    incremental = _calculate(24, autosens=1.2)
    incorrect_full_recalculation = _calculate(87, autosens=1.2)
    assert incremental.used_params.effective_cr_g_per_u == 7.5
    assert incremental.meal_bolus_u == pytest.approx(3.2)
    assert incorrect_full_recalculation.meal_bolus_u == pytest.approx(11.6)


def test_case_8_high_iob_blocks_duplicate_correction_not_new_food():
    result = _calculate(24, autosens=1.2, iob=7.93, bg=160)
    food_only = _calculate(24, autosens=1.2, iob=7.93, bg=None)
    assert result.meal_bolus_u == pytest.approx(3.2)
    assert result.correction_u > 0
    assert result.iob_applied_to_correction_u == pytest.approx(result.correction_u)
    assert result.total_u_final == food_only.total_u_final
    assert result.total_u_final > 0


@pytest.mark.asyncio
async def test_case_9_coverage_survives_new_session_restart(coverage_db):
    first = await _import(coverage_db, {"carbs": 63})
    await _confirm(coverage_db, first, "calc-restart")
    async with coverage_db() as restarted_session:
        row = await get_meal_state(
            restarted_session, user_id=USER_ID, external_meal_id=MEAL_ID
        )
        assert state_context(row)["covered"]["carbs"] == 63


@pytest.mark.asyncio
async def test_case_10_duplicate_and_racing_confirmations_are_idempotent(coverage_db):
    context = await _import(coverage_db, {"carbs": 63})
    async with coverage_db() as session:
        first = await reserve_confirmation(
            session,
            user_id=USER_ID,
            external_meal_id=MEAL_ID,
            expected_revision=context["revision"],
            expected_covered=context["covered"],
            calculation_id="race-winner",
        )
    assert first.ok
    async with coverage_db() as session:
        duplicate = await reserve_confirmation(
            session,
            user_id=USER_ID,
            external_meal_id=MEAL_ID,
            expected_revision=context["revision"],
            expected_covered=context["covered"],
            calculation_id="race-loser",
        )
    assert not duplicate.ok
    assert duplicate.reason == "confirmation_in_progress"


@pytest.mark.asyncio
async def test_treatment_guard_rejects_revision_changed_after_reservation(coverage_db):
    context = await _import(coverage_db, {"carbs": 63})
    async with coverage_db() as session:
        reserved = await reserve_confirmation(
            session,
            user_id=USER_ID,
            external_meal_id=MEAL_ID,
            expected_revision=context["revision"],
            expected_covered=context["covered"],
            calculation_id="guarded-calculation",
        )
    assert reserved.ok

    await _import(coverage_db, {"carbs": 87})
    async with coverage_db() as session:
        guarded = await validate_confirmation_for_treatment(
            session,
            user_id=USER_ID,
            external_meal_id=MEAL_ID,
            expected_revision=context["revision"],
            expected_covered=context["covered"],
            calculation_id="guarded-calculation",
        )

    assert guarded.ok is False
    assert guarded.reason == "meal_revision_changed"


def test_partial_edited_dose_advances_only_food_coverage_and_keeps_correction_separate():
    after, fraction, food_u, correction_u = covered_after_confirmation(
        covered_before={"carbs": 0},
        delta={"carbs": 60},
        accepted_u=2,
        recommended_upfront_u=6,
        positive_correction_after_iob_u=2,
        round_step_u=0.1,
    )
    assert fraction == pytest.approx(0.5)
    assert after["carbs"] == 30
    assert food_u == 2
    assert correction_u == 0
