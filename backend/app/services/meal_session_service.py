from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.meal_session import MealSession, MealSessionEvent


ACTIVE_STATUS = "active"
TERMINAL_STATUSES = {"closed", "cancelled"}


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _event_to_dict(event: MealSessionEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "kind": event.kind,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "carbs_g": event.carbs_g,
        "fat_g": event.fat_g,
        "protein_g": event.protein_g,
        "fiber_g": event.fiber_g,
        "treatment_id": event.treatment_id,
        "accepted_insulin_u": event.accepted_insulin_u,
        "recommended_total_u": event.recommended_total_u,
        "recommended_meal_u": event.recommended_meal_u,
        "recommended_correction_u": event.recommended_correction_u,
        "iob_u": event.iob_u,
        "iob_applied_to_correction_u": event.iob_applied_to_correction_u,
        "payload": event.payload,
    }


def summarize_meal_session(row: MealSession) -> dict[str, Any]:
    events = list(row.events or [])
    plate_events = [event for event in events if event.kind == "carbs_added"]
    bolus_events = [event for event in events if event.kind == "bolus_recorded"]

    def total(items, attr: str) -> float:
        return round(sum(float(getattr(item, attr) or 0) for item in items), 2)

    return {
        "id": row.id,
        "status": row.status,
        "meal_slot": row.meal_slot,
        "label": row.label,
        "source": row.source,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        # These deliberately have different names/semantics. "Submitted" does
        # not claim the carbohydrates were physiologically covered.
        "carbs_recorded_g": total(plate_events, "carbs_g"),
        "carbs_submitted_for_bolus_g": total(bolus_events, "carbs_g"),
        "accepted_insulin_u": total(bolus_events, "accepted_insulin_u"),
        "event_count": len(events),
        "events": [_event_to_dict(event) for event in events],
    }


async def _load_session(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
) -> Optional[MealSession]:
    stmt = (
        select(MealSession)
        .options(selectinload(MealSession.events))
        .where(MealSession.id == session_id, MealSession.user_id == user_id)
        # The same AsyncSession may already hold this MealSession with an older
        # loaded events collection. Force refresh so summaries see newly
        # appended ledger events instead of the stale identity-map collection.
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalars().first()


async def get_active_meal_session(db: AsyncSession, user_id: str) -> Optional[MealSession]:
    stmt = (
        select(MealSession)
        .options(selectinload(MealSession.events))
        .where(MealSession.user_id == user_id, MealSession.status == ACTIVE_STATUS)
        .order_by(MealSession.started_at.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalars().first()


async def start_meal_session(
    db: AsyncSession,
    *,
    user_id: str,
    meal_slot: Optional[str] = None,
    label: Optional[str] = None,
    source: Optional[str] = "app",
) -> MealSession:
    active = await get_active_meal_session(db, user_id)
    if active is not None:
        return active

    now = _utc_naive_now()
    row = MealSession(
        id=str(uuid4()),
        user_id=user_id,
        started_at=now,
        updated_at=now,
        status=ACTIVE_STATUS,
        meal_slot=meal_slot,
        label=label,
        source=source,
    )
    db.add(row)
    await db.commit()
    return await _load_session(db, user_id=user_id, session_id=row.id)


async def get_meal_session(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
) -> Optional[MealSession]:
    return await _load_session(db, user_id=user_id, session_id=session_id)


async def _find_existing_event(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    dedupe_key: str,
) -> Optional[MealSessionEvent]:
    stmt = select(MealSessionEvent).where(
        MealSessionEvent.session_id == session_id,
        MealSessionEvent.dedupe_key == dedupe_key,
        MealSessionEvent.user_id == user_id,
    )
    return (await db.execute(stmt)).scalars().first()


async def record_meal_session_event(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    kind: str,
    dedupe_key: str,
    carbs_g: Optional[float] = None,
    fat_g: Optional[float] = None,
    protein_g: Optional[float] = None,
    fiber_g: Optional[float] = None,
    treatment_id: Optional[str] = None,
    accepted_insulin_u: Optional[float] = None,
    recommended_total_u: Optional[float] = None,
    recommended_meal_u: Optional[float] = None,
    recommended_correction_u: Optional[float] = None,
    iob_u: Optional[float] = None,
    iob_applied_to_correction_u: Optional[float] = None,
    payload: Optional[dict[str, Any]] = None,
) -> MealSessionEvent:
    meal = await _load_session(db, user_id=user_id, session_id=session_id)
    if meal is None:
        raise LookupError("meal_session_not_found")
    if meal.status != ACTIVE_STATUS:
        raise ValueError("meal_session_not_active")

    # Normal idempotent retries must not force a transaction rollback: a full
    # rollback expires unrelated ORM objects in the caller's AsyncSession and
    # can trigger MissingGreenlet on later attribute access. Check first, then
    # keep the DB unique constraint as the race-condition backstop.
    existing = await _find_existing_event(
        db,
        user_id=user_id,
        session_id=session_id,
        dedupe_key=dedupe_key,
    )
    if existing is not None:
        return existing

    event = MealSessionEvent(
        id=str(uuid4()),
        session_id=session_id,
        user_id=user_id,
        created_at=_utc_naive_now(),
        kind=kind,
        dedupe_key=dedupe_key,
        carbs_g=carbs_g,
        fat_g=fat_g,
        protein_g=protein_g,
        fiber_g=fiber_g,
        treatment_id=treatment_id,
        accepted_insulin_u=accepted_insulin_u,
        recommended_total_u=recommended_total_u,
        recommended_meal_u=recommended_meal_u,
        recommended_correction_u=recommended_correction_u,
        iob_u=iob_u,
        iob_applied_to_correction_u=iob_applied_to_correction_u,
        payload=payload,
    )

    try:
        # Use a savepoint for the uniqueness race so a competing retry cannot
        # poison/expire the caller's outer transaction.
        async with db.begin_nested():
            db.add(event)
            await db.flush()
            meal.updated_at = event.created_at
        await db.commit()
        await db.refresh(event)
        return event
    except IntegrityError:
        # The nested transaction has already rolled back only the savepoint.
        # A concurrent writer may have inserted the same dedupe key first.
        existing = await _find_existing_event(
            db,
            user_id=user_id,
            session_id=session_id,
            dedupe_key=dedupe_key,
        )
        if existing is None:
            await db.rollback()
            raise
        return existing


async def record_carbs_added(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    client_event_id: str,
    carbs_g: float,
    fat_g: float = 0,
    protein_g: float = 0,
    fiber_g: float = 0,
    payload: Optional[dict[str, Any]] = None,
) -> MealSessionEvent:
    return await record_meal_session_event(
        db,
        user_id=user_id,
        session_id=session_id,
        kind="carbs_added",
        dedupe_key=f"carbs:{client_event_id}",
        carbs_g=carbs_g,
        fat_g=fat_g,
        protein_g=protein_g,
        fiber_g=fiber_g,
        payload=payload,
    )


async def record_bolus_in_session(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    treatment_id: str,
    carbs_g: float,
    accepted_insulin_u: float,
    calculation_trace: Optional[dict[str, Any]] = None,
) -> MealSessionEvent:
    trace = calculation_trace or {}
    snapshot = trace.get("snapshot") or {}
    return await record_meal_session_event(
        db,
        user_id=user_id,
        session_id=session_id,
        kind="bolus_recorded",
        dedupe_key=f"treatment:{treatment_id}",
        carbs_g=carbs_g,
        treatment_id=treatment_id,
        accepted_insulin_u=accepted_insulin_u,
        recommended_total_u=snapshot.get("recommended_u"),
        recommended_meal_u=snapshot.get("meal_component_u"),
        recommended_correction_u=snapshot.get("correction_component_u"),
        iob_u=snapshot.get("iob_u"),
        iob_applied_to_correction_u=snapshot.get("iob_applied_to_correction_u"),
        payload={
            "trace_schema_version": snapshot.get("schema_version"),
            "source": snapshot.get("source"),
            "accepted_u": snapshot.get("accepted_u"),
        },
    )


async def finish_meal_session(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    status: str,
) -> MealSession:
    if status not in TERMINAL_STATUSES:
        raise ValueError("invalid_meal_session_status")
    meal = await _load_session(db, user_id=user_id, session_id=session_id)
    if meal is None:
        raise LookupError("meal_session_not_found")
    now = _utc_naive_now()
    meal.status = status
    meal.updated_at = now
    meal.closed_at = now
    await db.commit()
    return await _load_session(db, user_id=user_id, session_id=session_id)
