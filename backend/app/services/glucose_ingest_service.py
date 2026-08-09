from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.glucose_reading import GlucoseReadingDB


DIRECT_SOURCES = {"dexcom_android", "g7_direct_watch"}
REMOTE_SOURCES = {"nightscout", "dexcom_share"}
ALLOWED_SOURCES = DIRECT_SOURCES | REMOTE_SOURCES | {"manual"}

BLOCKED_SENSOR_STATES = {
    "WARMUP",
    "STARTUP",
    "STOPPED",
    "FAILED",
    "ERROR",
    "EXPIRED",
    "NO_READINGS",
    "NOT_ACTIVE",
    "SENSOR_FAILED",
}


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def epoch_to_utc(value: int | float) -> datetime:
    # Mobile v1 uses seconds; Nightscout commonly uses milliseconds.
    seconds = float(value) / 1000.0 if float(value) > 10_000_000_000 else float(value)
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _bounded_identifier(value: Optional[str], max_length: int = 160) -> Optional[str]:
    if not value:
        return None
    normalized = str(value).strip()
    if len(normalized) <= max_length:
        return normalized
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_reading_uid(
    *,
    user_id: str,
    source: str,
    measured_at: datetime,
    glucose_mgdl: int,
    reading_uid: Optional[str] = None,
    sensor_session_id: Optional[str] = None,
    sequence: Optional[int] = None,
) -> str:
    supplied = _bounded_identifier(reading_uid)
    if supplied:
        return supplied

    if sensor_session_id and sequence is not None:
        identity = f"{user_id}|{source}|{sensor_session_id}|{sequence}"
    else:
        identity = (
            f"{user_id}|{source}|{int(as_utc(measured_at).timestamp() * 1000)}|"
            f"{glucose_mgdl}"
        )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class GlucoseIngestData:
    glucose_mgdl: int
    measured_at: datetime
    source: str
    schema_version: int = 1
    reading_uid: Optional[str] = None
    trend_arrow: Optional[str] = None
    trend_rate: Optional[float] = None
    sensor_state: Optional[str] = None
    display_only: bool = False
    historical: bool = False
    timestamp_uncertain: bool = False
    sensor_session_id: Optional[str] = None
    sequence: Optional[int] = None
    sensor_type: Optional[str] = None
    source_package: Optional[str] = None
    origin_installation_id: Optional[str] = None
    received_at: Optional[datetime] = None
    received_at_watch: Optional[datetime] = None
    received_at_phone: Optional[datetime] = None
    outbox_sequence: Optional[int] = None
    decision_eligible: bool = True


@dataclass(slots=True)
class GlucoseIngestResult:
    status: str
    reading: GlucoseReadingDB
    duplicate: bool = False


def validate_ingest(data: GlucoseIngestData, now: Optional[datetime] = None) -> tuple[str, Optional[str], bool, bool]:
    now = as_utc(now or datetime.now(timezone.utc))
    measured_at = as_utc(data.measured_at)
    age = now - measured_at
    source = (data.source or "").strip().lower()
    decision_eligible = bool(data.decision_eligible and source != "g7_direct_watch")

    reason: Optional[str] = None
    if source not in ALLOWED_SOURCES:
        reason = "unsupported_source"
    elif not 1 <= int(data.glucose_mgdl) <= 400:
        reason = "glucose_out_of_range"
    elif measured_at > now + timedelta(minutes=5):
        reason = "timestamp_in_future"
    elif measured_at < now - timedelta(days=7):
        reason = "timestamp_too_old"
    elif data.display_only:
        reason = "display_only"
    elif (data.sensor_state or "").strip().upper() in BLOCKED_SENSOR_STATES:
        reason = f"sensor_state_{(data.sensor_state or '').strip().lower()}"

    historical = bool(data.historical or age > timedelta(minutes=15))
    usable = (
        reason is None
        and not historical
        and not data.timestamp_uncertain
        and decision_eligible
        and 40 <= int(data.glucose_mgdl) <= 400
    )
    return ("accepted" if reason is None else "rejected", reason, usable, historical)


async def ingest_glucose_reading(
    session: AsyncSession,
    user_id: str,
    data: GlucoseIngestData,
    *,
    sync_to_nightscout: bool = True,
    flush: bool = True,
) -> GlucoseIngestResult:
    source = data.source.strip().lower()
    measured_at = as_utc(data.measured_at)
    received_at = as_utc(data.received_at or datetime.now(timezone.utc))
    session_id = _bounded_identifier(data.sensor_session_id)
    uid = build_reading_uid(
        user_id=user_id,
        source=source,
        measured_at=measured_at,
        glucose_mgdl=int(data.glucose_mgdl),
        reading_uid=data.reading_uid,
        sensor_session_id=session_id,
        sequence=data.sequence,
    )

    existing = (
        await session.execute(
            select(GlucoseReadingDB).where(
                GlucoseReadingDB.user_id == user_id,
                GlucoseReadingDB.reading_uid == uid,
            )
        )
    ).scalars().first()
    origin_installation_id = _bounded_identifier(data.origin_installation_id)
    if (
        existing is None
        and origin_installation_id
        and session_id
        and data.sequence is not None
    ):
        existing = (
            await session.execute(
                select(GlucoseReadingDB).where(
                    GlucoseReadingDB.user_id == user_id,
                    GlucoseReadingDB.source == source,
                    GlucoseReadingDB.origin_installation_id == origin_installation_id,
                    GlucoseReadingDB.sensor_session_id == session_id,
                    GlucoseReadingDB.sequence == data.sequence,
                )
            )
        ).scalars().first()
    if existing:
        # A point may first arrive as backfill and later as a live reading. Keep
        # the stable UID, but allow the live copy to restore dosing metadata.
        validation_status, validation_reason, usable, historical = validate_ingest(data)
        if existing.validation_status == "accepted" and validation_status == "accepted":
            existing.historical = historical
            existing.timestamp_uncertain = bool(data.timestamp_uncertain)
            existing.usable_for_dosing = usable
            existing.validation_reason = validation_reason
            existing.received_at = max(as_utc(existing.received_at), received_at)
            existing.trend_arrow = _bounded_identifier(data.trend_arrow, 64) or existing.trend_arrow
            existing.trend_rate = data.trend_rate if data.trend_rate is not None else existing.trend_rate
            if source == "dexcom_android" and sync_to_nightscout and existing.sync_status == "not_required":
                existing.sync_status = "pending"
            if flush:
                await session.flush()
        return GlucoseIngestResult(status="duplicate", reading=existing, duplicate=True)

    validation_status, validation_reason, usable, historical = validate_ingest(data)
    decision_eligible = bool(data.decision_eligible and source != "g7_direct_watch")
    if source == "dexcom_android" and sync_to_nightscout and validation_status == "accepted":
        sync_status = "pending"
    elif source == "nightscout":
        sync_status = "synced"
    else:
        sync_status = "not_required"

    row = GlucoseReadingDB(
        user_id=user_id,
        reading_uid=uid,
        schema_version=max(1, int(data.schema_version or 1)),
        glucose_mgdl=int(data.glucose_mgdl),
        measured_at=measured_at,
        received_at=received_at,
        received_at_watch=as_utc(data.received_at_watch) if data.received_at_watch else None,
        received_at_phone=as_utc(data.received_at_phone) if data.received_at_phone else None,
        source=source,
        source_package=_bounded_identifier(data.source_package),
        origin_installation_id=origin_installation_id,
        sensor_type=_bounded_identifier(data.sensor_type, 40),
        sensor_session_id=session_id,
        sequence=data.sequence,
        outbox_sequence=data.outbox_sequence,
        trend_arrow=_bounded_identifier(data.trend_arrow, 64),
        trend_rate=data.trend_rate,
        sensor_state=_bounded_identifier(data.sensor_state, 64),
        display_only=bool(data.display_only),
        historical=historical,
        timestamp_uncertain=bool(data.timestamp_uncertain),
        validation_status=validation_status,
        validation_reason=validation_reason,
        usable_for_dosing=usable,
        decision_eligible=decision_eligible,
        sync_status=sync_status,
    )
    session.add(row)
    if flush:
        await session.flush()
    return GlucoseIngestResult(status=validation_status, reading=row)


async def latest_local_readings(
    session: AsyncSession,
    user_id: str,
    *,
    limit: int = 100,
) -> list[GlucoseReadingDB]:
    return list(
        (
            await session.execute(
                select(GlucoseReadingDB)
                .where(GlucoseReadingDB.user_id == user_id)
                .order_by(GlucoseReadingDB.measured_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )
