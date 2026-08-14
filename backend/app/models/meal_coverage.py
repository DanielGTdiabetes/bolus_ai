from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MealCoverageState(Base):
    """Persistent dosing coverage for one external meal identity.

    Imported nutrition is mutable.  This row deliberately separates the latest
    source totals from the totals backed by a confirmed treatment.
    """

    __tablename__ = "meal_coverage_states"
    __table_args__ = (
        UniqueConstraint("user_id", "meal_key", name="uq_meal_coverage_user_key"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    meal_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_meal_id: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="unknown")

    current_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    current_nutrition: Mapped[dict] = mapped_column(JSON, nullable=False)
    covered_nutrition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    last_confirmed_bolus: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_calculation_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    last_treatment_id: Mapped[str | None] = mapped_column(String, nullable=True)

    confirmation_in_progress_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    confirmation_in_progress_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )
