from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import Base


class NightPatternProfile(Base):
    __tablename__ = "night_pattern_profiles"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    bucket_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=75)
    sample_days: Mapped[int] = mapped_column(Integer, nullable=False, default=18)
    sample_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    pattern: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    dispersion_iqr: Mapped[Optional[float]] = mapped_column(nullable=True)
