import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Float, Integer, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import Base


class IsfRun(Base):
    __tablename__ = "isf_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    n_events: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    diff_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    flags: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list)
