from datetime import datetime, timezone
import uuid
from typing import Optional

from sqlalchemy import String, Float, DateTime, Enum, Column, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class NutritionDraftDB(Base):
    __tablename__ = "nutrition_drafts"
    __table_args__ = {'extend_existing': True}

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, index=True)
    
    status: Mapped[str] = mapped_column(String, default="active") # active, closed, discarded
    
    carbs: Mapped[float] = mapped_column(Float, default=0.0)
    fat: Mapped[float] = mapped_column(Float, default=0.0)
    protein: Mapped[float] = mapped_column(Float, default=0.0)
    fiber: Mapped[float] = mapped_column(Float, default=0.0)
    
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    last_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
