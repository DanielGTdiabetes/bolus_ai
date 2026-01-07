from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AutosensRun(Base):
    __tablename__ = "autosens_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    ratio: Mapped[float] = mapped_column(Float, nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    input_summary_json: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    clamp_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason_flags: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list)
    enabled_state: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
