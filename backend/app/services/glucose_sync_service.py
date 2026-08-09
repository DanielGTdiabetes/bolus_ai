from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.models.glucose_reading import GlucoseReadingDB
from app.services.glucose_ingest_service import as_utc
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config


logger = logging.getLogger(__name__)


async def _nightscout_client_for_user(
    session: AsyncSession, user_id: str
) -> Optional[NightscoutClient]:
    stored = await get_ns_config(session, user_id)
    settings = get_settings()
    if stored and stored.enabled and stored.url and stored.api_secret:
        return NightscoutClient(
            stored.url,
            stored.api_secret,
            timeout_seconds=settings.nightscout.timeout_seconds,
        )
    if settings.nightscout.base_url and (
        settings.nightscout.api_secret or settings.nightscout.token
    ):
        return NightscoutClient(
            str(settings.nightscout.base_url),
            settings.nightscout.token,
            api_secret=settings.nightscout.api_secret,
            timeout_seconds=settings.nightscout.timeout_seconds,
        )
    return None


async def sync_glucose_reading(
    session: AsyncSession,
    reading: GlucoseReadingDB,
    *,
    client: Optional[NightscoutClient] = None,
) -> str:
    if reading.validation_status != "accepted":
        reading.sync_status = "not_required"
        return reading.sync_status
    if reading.sync_status in {"synced", "duplicate", "not_required"}:
        return reading.sync_status

    owns_client = client is None
    client = client or await _nightscout_client_for_user(session, reading.user_id)
    if client is None:
        reading.sync_status = "pending"
        reading.sync_error = "nightscout_not_configured"
        return reading.sync_status

    try:
        reading.sync_attempts += 1
        result = await client.upload_sgv(
            glucose_mgdl=reading.glucose_mgdl,
            timestamp_ms=int(as_utc(reading.measured_at).timestamp() * 1000),
            direction=reading.trend_arrow or "NONE",
        )
        status = str(result.get("status") or "uploaded")
        reading.sync_status = "duplicate" if status == "duplicate" else "synced"
        reading.synced_at = datetime.now(timezone.utc)
        reading.sync_error = None
    except Exception as exc:
        reading.sync_status = "failed"
        reading.sync_error = type(exc).__name__
        logger.warning(
            "Glucose Nightscout sync failed reading=%s user=%s error=%s",
            reading.reading_uid,
            reading.user_id,
            type(exc).__name__,
        )
    finally:
        if owns_client and client:
            await client.aclose()
    return reading.sync_status


async def sync_pending_glucose_readings(
    session: AsyncSession,
    *,
    user_id: Optional[str] = None,
    limit: int = 100,
) -> dict[str, int]:
    query = (
        select(GlucoseReadingDB)
        .where(GlucoseReadingDB.sync_status.in_(("pending", "failed")))
        .order_by(GlucoseReadingDB.received_at.asc())
        .limit(limit)
    )
    if user_id:
        query = query.where(GlucoseReadingDB.user_id == user_id)
    rows = list((await session.execute(query)).scalars().all())

    stats = {"processed": 0, "synced": 0, "duplicate": 0, "failed": 0, "pending": 0}
    clients: dict[str, Optional[NightscoutClient]] = {}
    try:
        for row in rows:
            if row.user_id not in clients:
                clients[row.user_id] = await _nightscout_client_for_user(session, row.user_id)
            status = await sync_glucose_reading(
                session, row, client=clients[row.user_id]
            )
            stats["processed"] += 1
            stats[status if status in stats else "failed"] += 1
        await session.commit()
    finally:
        for client in clients.values():
            if client:
                await client.aclose()
    return stats
