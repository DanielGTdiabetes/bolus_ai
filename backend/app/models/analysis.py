
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Float, Integer, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

class BolusPostAnalysis(Base):
    __tablename__ = "bolus_post_analysis"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    bolus_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meal_slot: Mapped[str] = mapped_column(String, nullable=False) # breakfast|lunch|dinner|snack
    window_h: Mapped[int] = mapped_column(Integer, nullable=False) # 2, 3, 5
    
    bg_mgdl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bg_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    target_mgdl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    result: Mapped[str] = mapped_column(String, nullable=False) # short|ok|over|missing
    iob_status: Mapped[str] = mapped_column(String, nullable=False) # ok|unavailable|partial
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "bolus_at", "window_h", name="uq_user_bolus_window"),
    )
