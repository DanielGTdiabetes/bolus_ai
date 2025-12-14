import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Float, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.core.db import Base

class BasalEntry(Base):
    __tablename__ = "basal_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    basal_type: Mapped[str] = mapped_column(String)  # "glargine", "degludec", "detemir", "other"
    units: Mapped[float] = mapped_column(Float)
    effective_hours: Mapped[int] = mapped_column(Integer, default=24)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)

class BasalCheckin(Base):
    __tablename__ = "basal_checkins"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    bg_mgdl: Mapped[float] = mapped_column(Float)
    bg_age_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trend: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ns_url_hash: Mapped[str] = mapped_column(String)
