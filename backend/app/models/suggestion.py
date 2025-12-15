
import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import String, Integer, DateTime, Boolean, text, Float, ForeignKey, JSON, CheckConstraint, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.db import Base

class ParameterSuggestion(Base):
    __tablename__ = "parameter_suggestion"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    meal_slot: Mapped[str] = mapped_column(String, nullable=False) # breakfast|lunch|dinner|snack
    parameter: Mapped[str] = mapped_column(String, nullable=False) # icr|isf|target
    direction: Mapped[str] = mapped_column(String, nullable=False) # increase|decrease|review
    
    reason: Mapped[str] = mapped_column(String, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending") # pending|accepted|rejected
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(String, nullable=True) # accepted by user | rejection reason

    # Partial index implementation in SQLAlchemy is often DB specific. 
    # Logic in code will enforce: don't create if pending exists.
    # But we can try to define a UniqueConstraint if the DB supports it with condition.
    # PG supports filtered unique indexes.
    
    __table_args__ = (
        # We enforce "one pending suggestion per slot+param" to avoid spam
        # Use partial unique index
        Index('uq_pending_suggestion', 'user_id', 'meal_slot', 'parameter', 'status', unique=True, postgresql_where=text("status = 'pending'")),
    )
