import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GlucoseReadingDB(Base):
    """Canonical glucose reading received from any configured CGM source."""

    __tablename__ = "glucose_readings"
    __table_args__ = (
        UniqueConstraint("user_id", "reading_uid", name="uq_glucose_reading_user_uid"),
        UniqueConstraint(
            "user_id",
            "source",
            "origin_installation_id",
            "sensor_session_id",
            "sequence",
            name="uq_glucose_reading_sensor_sequence",
        ),
        Index("ix_glucose_readings_user_measured", "user_id", "measured_at"),
        Index("ix_glucose_readings_user_source_measured", "user_id", "source", "measured_at"),
        Index("ix_glucose_readings_sync_status", "sync_status", "received_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reading_uid: Mapped[str] = mapped_column(String(160), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    glucose_mgdl: Mapped[int] = mapped_column(Integer, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    received_at_watch: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at_phone: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_package: Mapped[str | None] = mapped_column(String(160), nullable=True)
    origin_installation_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sensor_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sensor_session_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outbox_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    trend_arrow: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trend_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    sensor_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    historical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timestamp_uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    validation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="accepted"
    )
    validation_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    usable_for_dosing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decision_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    sync_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="not_required"
    )
    sync_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )
