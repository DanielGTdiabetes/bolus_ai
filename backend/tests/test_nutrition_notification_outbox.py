from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.models.nutrition_notification_outbox import NutritionNotificationOutbox
from app.services.nutrition_notification_outbox import (
    DeliveryResult,
    enqueue_meal_notification,
    process_nutrition_notification_outbox,
)


@pytest.fixture()
async def outbox_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'outbox.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _enqueue(factory, event_id="meal-1", kind="meal_created"):
    async with factory() as session:
        item = await enqueue_meal_notification(
            session,
            event_id=event_id,
            notification_kind=kind,
            user_id="admin",
            sync_id="sync-123",
            payload={"origin_id": event_id, "carbs": 30, "source": "Importado"},
        )
        await session.commit()
        return item.id


async def _row(factory, item_id):
    async with factory() as session:
        return await session.get(NutritionNotificationOutbox, item_id)


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_for_event_kind_and_channel(outbox_factory):
    first_id = await _enqueue(outbox_factory)
    second_id = await _enqueue(outbox_factory)

    async with outbox_factory() as session:
        count = (await session.execute(select(func.count(NutritionNotificationOutbox.id)))).scalar_one()
    assert first_id == second_id
    assert count == 1


@pytest.mark.asyncio
async def test_sent_message_is_persisted_and_never_delivered_twice(outbox_factory):
    item_id = await _enqueue(outbox_factory)
    calls = []

    async def deliver(payload):
        calls.append(payload["origin_id"])
        return DeliveryResult(status="sent", telegram_message_id="991")

    first = await process_nutrition_notification_outbox(outbox_factory, deliver)
    second = await process_nutrition_notification_outbox(outbox_factory, deliver)
    row = await _row(outbox_factory, item_id)

    assert first["sent"] == 1
    assert second["processed"] == 0
    assert calls == ["meal-1"]
    assert row.status == "sent"
    assert row.telegram_message_id == "991"


@pytest.mark.asyncio
async def test_retryable_failure_uses_backoff_then_recovers(outbox_factory):
    item_id = await _enqueue(outbox_factory)
    outcomes = [
        DeliveryResult(status="retry_scheduled", error="RetryAfter", retry_after_seconds=60),
        DeliveryResult(status="sent", telegram_message_id="992"),
    ]

    async def deliver(_payload):
        return outcomes.pop(0)

    first = await process_nutrition_notification_outbox(outbox_factory, deliver)
    assert first["retry_scheduled"] == 1
    row = await _row(outbox_factory, item_id)
    assert row.status == "retry_scheduled"
    assert row.attempt_count == 1

    async with outbox_factory() as session:
        row = await session.get(NutritionNotificationOutbox, item_id)
        row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
        await session.commit()

    second = await process_nutrition_notification_outbox(outbox_factory, deliver)
    row = await _row(outbox_factory, item_id)
    assert second["sent"] == 1
    assert row.status == "sent"
    assert row.attempt_count == 2


@pytest.mark.asyncio
async def test_ambiguous_timeout_is_terminal_and_not_blindly_retried(outbox_factory):
    item_id = await _enqueue(outbox_factory)
    calls = 0

    async def deliver(_payload):
        nonlocal calls
        calls += 1
        return DeliveryResult(status="delivery_unknown", error="TimedOut")

    first = await process_nutrition_notification_outbox(outbox_factory, deliver)
    second = await process_nutrition_notification_outbox(outbox_factory, deliver)
    row = await _row(outbox_factory, item_id)

    assert first["delivery_unknown"] == 1
    assert second["processed"] == 0
    assert calls == 1
    assert row.status == "delivery_unknown"
    assert row.telegram_message_id is None


@pytest.mark.asyncio
async def test_restart_processes_persisted_queued_item(outbox_factory):
    item_id = await _enqueue(outbox_factory, event_id="meal-after-restart")

    async def deliver(_payload):
        return DeliveryResult(status="sent", telegram_message_id="restart-1")

    stats = await process_nutrition_notification_outbox(outbox_factory, deliver)
    row = await _row(outbox_factory, item_id)
    assert stats["sent"] == 1
    assert row.status == "sent"


@pytest.mark.asyncio
async def test_concurrent_processors_claim_only_one_delivery(outbox_factory):
    item_id = await _enqueue(outbox_factory, event_id="meal-concurrent")
    calls = 0

    async def deliver(_payload):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return DeliveryResult(status="sent", telegram_message_id="concurrent-1")

    results = await asyncio.gather(
        process_nutrition_notification_outbox(outbox_factory, deliver, limit=1),
        process_nutrition_notification_outbox(outbox_factory, deliver, limit=1),
    )
    row = await _row(outbox_factory, item_id)
    assert sum(result["processed"] for result in results) == 1
    assert calls == 1
    assert row.status == "sent"
