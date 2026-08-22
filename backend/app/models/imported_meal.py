from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImportedMeal(Base):
    """Durable, reviewable representation of one meal from a mutable source."""

    __tablename__ = "imported_meals"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source", "source_reference",
            name="uq_imported_meal_source_reference",
        ),
        Index("ix_imported_meal_status_seen", "status", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    meal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    meal_type: Mapped[str] = mapped_column(String(40), nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW", index=True)

    foods: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_carbs: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    calculated_carbs: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    previous_calculated_carbs: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    protein: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fiber: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    stable_read_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_stable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pending_source_version: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    discarded_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    treatment_status: Mapped[str] = mapped_column(String(24), nullable=False, default="UNTREATED")
    draft_treatment_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    linked_bolus_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    last_bolus_units: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_bolus_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportedMealSnapshot(Base):
    """Short diagnostic history; payload is normalized and never contains credentials."""

    __tablename__ = "imported_meal_snapshots"
    __table_args__ = (
        Index("ix_imported_meal_snapshot_meal_seen", "meal_id", "seen_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    meal_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sync_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utc_now)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_carbs: Mapped[float] = mapped_column(Float, nullable=False)
    calculated_carbs: Mapped[float] = mapped_column(Float, nullable=False)
    foods: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    timing: Mapped[dict | None] = mapped_column(JSON, nullable=True)
