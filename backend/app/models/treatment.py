from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class Treatment(Base):
    __tablename__ = "treatments"

    id: Mapped[str] = mapped_column(String, primary_key=True, comment="UUID or Unique ID")
    user_id: Mapped[str] = mapped_column(String, nullable=True, index=True)
    
    event_type: Mapped[str] = mapped_column(String, nullable=False, default="Meal Bolus")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    
    insulin: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    carbs: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fat: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    protein: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fiber: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    glucose: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="BG at time of bolus")
    duration: Mapped[float] = mapped_column(Float, default=0.0, comment="Duration in minutes (0=instant)")
    
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entered_by: Mapped[str] = mapped_column(String, nullable=True)
    
    # Sync Status
    is_uploaded: Mapped[bool] = mapped_column(Boolean, default=False)
    nightscout_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
