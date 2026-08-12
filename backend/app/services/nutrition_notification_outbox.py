from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Iterable

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models.nutrition_notification_outbox import NutritionNotificationOutbox


logger = logging.getLogger(__name__)

OUTBOX_CHANNEL = "telegram"
RETRYABLE_STATUSES = ("queued", "retry_scheduled")
TERMINAL_STATUSES = ("sent", "delivery_unknown", "failed")
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (30, 120, 600, 1800, 3600)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    telegram_message_id: str | None = None
    error: str | None = None
    retry_after_seconds: int | None = None


def _naive_if_sqlite(session: AsyncSession, value: datetime) -> datetime:
    bind = session.get_bind()
    return value.replace(tzinfo=None) if bind.dialect.name == "sqlite" else value


def _pending_clause(now: datetime):
    return and_(
        NutritionNotificationOutbox.status.in_(RETRYABLE_STATUSES),
        NutritionNotificationOutbox.next_attempt_at <= now,
    )


async def enqueue_meal_notification(
    session: AsyncSession,
    *,
    event_id: str,
    notification_kind: str,
    user_id: str,
    sync_id: str | None,
    payload: dict,
) -> NutritionNotificationOutbox:
    values = {
        "event_id": event_id,
        "notification_kind": notification_kind,
        "channel": OUTBOX_CHANNEL,
        "sync_id": sync_id,
        "user_id": user_id,
        "payload": payload,
        "status": "queued",
        "attempt_count": 0,
        "next_attempt_at": _naive_if_sqlite(session, utc_now()),
    }
    if session.get_bind().dialect.name == "postgresql":
        stmt = pg_insert(NutritionNotificationOutbox).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_nutrition_notification_event_kind_channel",
            set_={
                "sync_id": stmt.excluded.sync_id,
                "user_id": stmt.excluded.user_id,
                "payload": stmt.excluded.payload,
                "updated_at": utc_now(),
            },
        ).returning(NutritionNotificationOutbox.id)
        outbox_id = (await session.execute(stmt)).scalar_one()
        return await session.get(NutritionNotificationOutbox, outbox_id)

    existing_stmt = select(NutritionNotificationOutbox).where(
        NutritionNotificationOutbox.event_id == event_id,
        NutritionNotificationOutbox.notification_kind == notification_kind,
        NutritionNotificationOutbox.channel == OUTBOX_CHANNEL,
    )
    existing = (await session.execute(existing_stmt)).scalars().first()
    if existing:
        existing.sync_id = sync_id or existing.sync_id
        existing.user_id = user_id
        existing.payload = payload
        session.add(existing)
        return existing

    item = NutritionNotificationOutbox(**values)
    session.add(item)
    await session.flush()
    return item


async def notification_status_for_events(
    session: AsyncSession,
    event_ids: Iterable[str],
) -> str:
    ids = list(dict.fromkeys(event_ids))
    if not ids:
        return "not_required"
    rows = (
        await session.execute(
            select(NutritionNotificationOutbox.status).where(
                NutritionNotificationOutbox.event_id.in_(ids)
            )
        )
    ).scalars().all()
    if not rows:
        return "not_required"
    statuses = set(rows)
    if "delivery_unknown" in statuses:
        return "delivery_unknown"
    if statuses <= {"sent"}:
        return "sent"
    if "failed" in statuses:
        return "failed"
    if "retry_scheduled" in statuses:
        return "retry_scheduled"
    return "queued"


async def _claim_one(session: AsyncSession) -> NutritionNotificationOutbox | None:
    now = _naive_if_sqlite(session, utc_now())
    query: Select = (
        select(NutritionNotificationOutbox.id)
        .where(_pending_clause(now))
        .order_by(
            NutritionNotificationOutbox.next_attempt_at,
            NutritionNotificationOutbox.created_at,
        )
        .limit(1)
    )
    candidate_id = (await session.execute(query)).scalar_one_or_none()
    if not candidate_id:
        return None

    claimed = await session.execute(
        update(NutritionNotificationOutbox)
        .where(
            NutritionNotificationOutbox.id == candidate_id,
            _pending_clause(now),
        )
        .values(
            status="delivery_unknown",
            attempt_count=NutritionNotificationOutbox.attempt_count + 1,
            last_attempt_at=now,
            last_error="claimed_not_sent",
            updated_at=now,
        )
    )
    if claimed.rowcount != 1:
        await session.rollback()
        return None
    await session.commit()
    return await session.get(NutritionNotificationOutbox, candidate_id)


def _retry_delay(attempt_count: int, requested: int | None) -> int:
    if requested is not None:
        return max(1, min(int(requested), 24 * 60 * 60))
    index = min(max(attempt_count - 1, 0), len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[index]


async def _complete(
    session: AsyncSession,
    item_id: str,
    result: DeliveryResult,
) -> None:
    item = await session.get(NutritionNotificationOutbox, item_id)
    if not item:
        return
    now = _naive_if_sqlite(session, utc_now())
    item.last_error = result.error
    item.updated_at = now
    if result.status == "sent":
        item.status = "sent"
        item.sent_at = now
        item.telegram_message_id = result.telegram_message_id
    elif result.status == "delivery_unknown":
        item.status = "delivery_unknown"
    elif result.status == "failed" or item.attempt_count >= MAX_ATTEMPTS:
        item.status = "failed"
    else:
        item.status = "retry_scheduled"
        delay = _retry_delay(item.attempt_count, result.retry_after_seconds)
        item.next_attempt_at = now + timedelta(seconds=delay)
    session.add(item)
    await session.commit()


async def process_nutrition_notification_outbox(
    session_factory: Callable[[], AsyncSession],
    deliver: Callable[[dict], Awaitable[DeliveryResult]],
    *,
    limit: int = 25,
) -> dict[str, int]:
    stats = {"processed": 0, "sent": 0, "retry_scheduled": 0, "delivery_unknown": 0, "failed": 0}
    for _ in range(limit):
        async with session_factory() as claim_session:
            item = await _claim_one(claim_session)
        if item is None:
            break

        try:
            result = await deliver(dict(item.payload))
        except Exception as error:  # Defensive: known Telegram errors are classified by the delivery adapter.
            result = DeliveryResult(status="delivery_unknown", error=f"{type(error).__name__}: {error}")

        async with session_factory() as completion_session:
            await _complete(completion_session, item.id, result)
        stats["processed"] += 1
        stats[result.status] = stats.get(result.status, 0) + 1
        logger.info(
            "nutrition_notification_outbox event_id=%s sync_id=%s status=%s attempt=%s message_id=%s",
            item.event_id,
            item.sync_id,
            result.status,
            item.attempt_count,
            result.telegram_message_id,
        )
    return stats
