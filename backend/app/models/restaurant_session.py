
import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import String, Float, Integer, DateTime, UniqueConstraint, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import Base

class RestaurantSessionV2(Base):
    __tablename__ = "restaurant_sessions_v2"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    # Store session-level aggregates
    expected_carbs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_carbs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta_carbs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    expected_fat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_protein: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    actual_fat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_protein: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # JSON blobs for flexible schema
    items_json: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default={}) # Raw menu items
    plates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=[]) # List of plate analysis results
    warnings_json: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=[])

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # For "Learning" - simple flag if this session was "Good" or "Bad" outcome (can be filled later)
    outcome_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) 

    __table_args__ = {'extend_existing': True}
