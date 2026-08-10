from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class MealSession(Base):
    __tablename__ = "meal_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", index=True)
    meal_slot: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    events = relationship(
        "MealSessionEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MealSessionEvent.created_at",
    )


class MealSessionEvent(Base):
    __tablename__ = "meal_session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "dedupe_key", name="uq_meal_session_event_dedupe"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("meal_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    dedupe_key: Mapped[str] = mapped_column(String, nullable=False)

    carbs_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fat_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    protein_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fiber_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    treatment_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    accepted_insulin_u: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recommended_total_u: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recommended_meal_u: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recommended_correction_u: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iob_u: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iob_applied_to_correction_u: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    session = relationship("MealSession", back_populates="events")
