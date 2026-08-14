from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meal_coverage import MealCoverageState


NUTRIENTS = ("carbs", "fat", "protein", "fiber")
ZERO_NUTRITION = {name: 0.0 for name in NUTRIENTS}
RESERVATION_TTL = timedelta(minutes=10)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value: object) -> Decimal:
    try:
        return max(Decimal("0"), Decimal(str(value or 0)))
    except Exception:
        return Decimal("0")


def normalize_nutrition(values: Mapping[str, object] | None) -> dict[str, float]:
    values = values or {}
    return {
        name: float(_decimal(values.get(name)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        for name in NUTRIENTS
    }


def meal_key(external_meal_id: str) -> str:
    return hashlib.sha256(external_meal_id.encode("utf-8")).hexdigest()


def nutrition_revision(
    nutrition: Mapping[str, object], explicit_revision: object | None = None
) -> str:
    if explicit_revision not in (None, ""):
        raw = f"external:{explicit_revision}"
    else:
        canonical = normalize_nutrition(nutrition)
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def treatment_id_for_calculation(calculation_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bolus-ai:meal-coverage:{calculation_id}"))


@dataclass(frozen=True)
class IncrementalNutrition:
    current: dict[str, float]
    covered: dict[str, float]
    delta: dict[str, float]
    reductions: dict[str, float]

    @property
    def is_update(self) -> bool:
        return any(value > 0 for value in self.covered.values())

    @property
    def has_new_nutrition(self) -> bool:
        return any(value > 0 for value in self.delta.values())


@dataclass(frozen=True)
class MealStateUpsert:
    state: MealCoverageState
    created: bool
    revision_changed: bool


def calculate_incremental_nutrition(
    current: Mapping[str, object], covered: Mapping[str, object] | None
) -> IncrementalNutrition:
    current_values = normalize_nutrition(current)
    covered_values = normalize_nutrition(covered)
    delta: dict[str, float] = {}
    reductions: dict[str, float] = {}
    for name in NUTRIENTS:
        current_value = _decimal(current_values[name])
        covered_value = _decimal(covered_values[name])
        delta[name] = float(max(Decimal("0"), current_value - covered_value))
        reductions[name] = float(max(Decimal("0"), covered_value - current_value))
    return IncrementalNutrition(current_values, covered_values, delta, reductions)


async def upsert_current_meal(
    session: AsyncSession,
    *,
    user_id: str,
    external_meal_id: str,
    source: str,
    revision: str,
    nutrition: Mapping[str, object],
) -> MealStateUpsert:
    key = meal_key(external_meal_id)
    row = (
        await session.execute(
            select(MealCoverageState).where(
                MealCoverageState.user_id == user_id,
                MealCoverageState.meal_key == key,
            )
        )
    ).scalars().first()
    normalized = normalize_nutrition(nutrition)
    now = _utc_now()
    previous_revision = row.current_revision if row is not None else None
    created = False
    if row is None:
        values = dict(
            id=str(uuid.uuid4()),
            user_id=user_id,
            meal_key=key,
            external_meal_id=external_meal_id,
            source=source or "unknown",
            current_revision=revision,
            current_nutrition=normalized,
            covered_nutrition=dict(ZERO_NUTRITION),
            revision_number=1,
            created_at=now,
            updated_at=now,
        )
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            insert_result = await session.execute(
                pg_insert(MealCoverageState)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_meal_coverage_user_key")
            )
        elif dialect == "sqlite":
            insert_result = await session.execute(
                sqlite_insert(MealCoverageState)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["user_id", "meal_key"])
            )
        else:
            session.add(MealCoverageState(**values))
            insert_result = None
            created = True
        await session.flush()
        if insert_result is not None:
            created = insert_result.rowcount == 1
        row = (
            await session.execute(
                select(MealCoverageState).where(
                    MealCoverageState.user_id == user_id,
                    MealCoverageState.meal_key == key,
                )
            )
        ).scalars().first()
        if row is None:  # pragma: no cover - unsupported dialect race fallback
            raise RuntimeError("meal coverage state could not be created")
        if not created:
            previous_revision = row.current_revision
        if row.current_revision == revision:
            return MealStateUpsert(
                state=row,
                created=created,
                revision_changed=created,
            )

    if row.current_revision != revision:
        row.revision_number = int(row.revision_number or 0) + 1
    row.external_meal_id = external_meal_id
    row.source = source or row.source
    row.current_revision = revision
    row.current_nutrition = normalized
    row.updated_at = now
    session.add(row)
    await session.flush()
    return MealStateUpsert(
        state=row,
        created=created,
        revision_changed=created or previous_revision != revision,
    )


async def get_meal_state(
    session: AsyncSession, *, user_id: str, external_meal_id: str, for_update: bool = False
) -> MealCoverageState | None:
    stmt = select(MealCoverageState).where(
        MealCoverageState.user_id == user_id,
        MealCoverageState.meal_key == meal_key(external_meal_id),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalars().first()


def state_context(row: MealCoverageState) -> dict:
    incremental = calculate_incremental_nutrition(
        row.current_nutrition, row.covered_nutrition
    )
    return {
        "state_id": row.id,
        "meal_id": row.external_meal_id,
        "meal_key": row.meal_key,
        "revision": row.current_revision,
        "revision_number": row.revision_number,
        "current": incremental.current,
        "covered": incremental.covered,
        "delta": incremental.delta,
        "reductions": incremental.reductions,
        "last_confirmed_bolus": row.last_confirmed_bolus,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "last_calculation_id": row.last_calculation_id,
    }


@dataclass(frozen=True)
class ReservationResult:
    ok: bool
    reason: str | None = None
    context: dict | None = None


async def reserve_confirmation(
    session: AsyncSession,
    *,
    user_id: str,
    external_meal_id: str,
    expected_revision: str,
    expected_covered: Mapping[str, object],
    calculation_id: str,
) -> ReservationResult:
    row = await get_meal_state(
        session, user_id=user_id, external_meal_id=external_meal_id, for_update=True
    )
    if row is None:
        return ReservationResult(False, "meal_state_missing")
    if row.current_revision != expected_revision:
        return ReservationResult(False, "meal_revision_changed", state_context(row))

    actual_covered = normalize_nutrition(row.covered_nutrition)
    if actual_covered != normalize_nutrition(expected_covered):
        return ReservationResult(False, "coverage_changed", state_context(row))
    if row.last_calculation_id == calculation_id:
        return ReservationResult(True, "already_confirmed", state_context(row))

    now = _utc_now()
    reserved_at = row.confirmation_in_progress_at
    if reserved_at and reserved_at.tzinfo is None:
        reserved_at = reserved_at.replace(tzinfo=timezone.utc)
    reservation_active = reserved_at and now - reserved_at < RESERVATION_TTL
    if (
        row.confirmation_in_progress_id
        and row.confirmation_in_progress_id != calculation_id
        and reservation_active
    ):
        return ReservationResult(False, "confirmation_in_progress", state_context(row))

    row.confirmation_in_progress_id = calculation_id
    row.confirmation_in_progress_at = now
    row.updated_at = now
    session.add(row)
    await session.commit()
    return ReservationResult(True, None, state_context(row))


def covered_after_confirmation(
    *,
    covered_before: Mapping[str, object],
    delta: Mapping[str, object],
    accepted_u: float,
    recommended_upfront_u: float,
    positive_correction_after_iob_u: float,
    round_step_u: float,
) -> tuple[dict[str, float], float, float, float]:
    """Allocate a confirmed dose without allowing correction IOB to cover food.

    The meal component is allocated first because this callback belongs to a
    meal recommendation.  A user-confirmed full rounded recommendation covers
    the whole incremental nutrition snapshot.  A lower edited dose advances
    coverage proportionally and never beyond the source totals.
    """

    accepted = max(0.0, float(accepted_u or 0))
    recommended = max(0.0, float(recommended_upfront_u or 0))
    correction = min(recommended, max(0.0, float(positive_correction_after_iob_u or 0)))
    nutrition_required = max(0.0, recommended - correction)
    tolerance = max(0.001, float(round_step_u or 0.0) / 2.0)

    if recommended > 0 and accepted + tolerance >= recommended:
        fraction = 1.0
        food_allocated = nutrition_required
        correction_allocated = correction
    elif nutrition_required > 0:
        food_allocated = min(accepted, nutrition_required)
        correction_allocated = min(correction, max(0.0, accepted - food_allocated))
        fraction = min(1.0, food_allocated / nutrition_required)
    else:
        food_allocated = 0.0
        correction_allocated = min(correction, accepted)
        fraction = 0.0

    before = normalize_nutrition(covered_before)
    increment = normalize_nutrition(delta)
    after = {
        name: float(
            (_decimal(before[name]) + (_decimal(increment[name]) * Decimal(str(fraction))))
            .quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        )
        for name in NUTRIENTS
    }
    return after, fraction, food_allocated, correction_allocated


async def finalize_confirmation(
    session: AsyncSession,
    *,
    user_id: str,
    external_meal_id: str,
    calculation_id: str,
    treatment_id: str,
    covered_after: Mapping[str, object],
    confirmed_bolus: float,
    confirmed_at: datetime | None = None,
) -> ReservationResult:
    row = await get_meal_state(
        session, user_id=user_id, external_meal_id=external_meal_id, for_update=True
    )
    if row is None:
        return ReservationResult(False, "meal_state_missing")
    if row.last_calculation_id == calculation_id:
        return ReservationResult(True, "already_confirmed", state_context(row))
    if row.confirmation_in_progress_id != calculation_id:
        return ReservationResult(False, "reservation_lost", state_context(row))

    now = confirmed_at or _utc_now()
    row.covered_nutrition = normalize_nutrition(covered_after)
    row.last_confirmed_bolus = max(0.0, float(confirmed_bolus or 0))
    row.confirmed_at = now
    row.last_calculation_id = calculation_id
    row.last_treatment_id = treatment_id
    row.confirmation_in_progress_id = None
    row.confirmation_in_progress_at = None
    row.updated_at = now
    session.add(row)
    await session.commit()
    return ReservationResult(True, None, state_context(row))


async def release_confirmation(
    session: AsyncSession,
    *,
    user_id: str,
    external_meal_id: str,
    calculation_id: str,
) -> None:
    row = await get_meal_state(
        session, user_id=user_id, external_meal_id=external_meal_id, for_update=True
    )
    if row and row.confirmation_in_progress_id == calculation_id:
        row.confirmation_in_progress_id = None
        row.confirmation_in_progress_at = None
        row.updated_at = _utc_now()
        session.add(row)
        await session.commit()
