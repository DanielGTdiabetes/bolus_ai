
import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import String, Integer, DateTime, Boolean, text, Float, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.core.db import Base

class SuggestionEvaluation(Base):
    __tablename__ = "suggestion_evaluation"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    suggestion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parameter_suggestion.id"), nullable=False, index=True)
    
    analysis_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    
    # pending | evaluated
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending") 
    
    # improved | worse | no_change | insufficient
    result: Mapped[str] = mapped_column(String, nullable=True) 
    
    summary: Mapped[str] = mapped_column(String, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
