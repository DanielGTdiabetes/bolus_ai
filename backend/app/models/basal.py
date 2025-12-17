
import uuid
from datetime import datetime, date as dt_date
from typing import Optional, Any
from sqlalchemy import String, Float, Integer, DateTime, Date, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import Base

class BasalEntry(Base):
    __table_args__ = {'extend_existing': True}
    __tablename__ = "basal_dose"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    
    # Columns matching basal_repo
    dose_u: Mapped[float] = mapped_column(Float)
    effective_from: Mapped[dt_date] = mapped_column(Date, nullable=False, default=dt_date.today)
    
    # Legacy/Model-only columns (likely NULL in DB)
    basal_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)  
    effective_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)

class BasalCheckin(Base):
    __tablename__ = "basal_checkin"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    checkin_date: Mapped[dt_date] = mapped_column(Date, nullable=False)
    
    bg_mgdl: Mapped[float] = mapped_column(Float, nullable=False)
    trend: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    age_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String, default="nightscout")
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('user_id', 'checkin_date', name='uq_basal_checkin_user_date'),
        {'extend_existing': True}
    )

class BasalNightSummary(Base):
    __tablename__ = "basal_night_summary"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    night_date: Mapped[dt_date] = mapped_column(Date, nullable=False)
    
    had_hypo: Mapped[bool] = mapped_column(Boolean, default=False)
    min_bg_mgdl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    events_below_70: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('user_id', 'night_date', name='uq_basal_night_user_date'),
        {'extend_existing': True}
    )

class BasalAdviceDaily(Base):
    __tablename__ = "basal_advice_daily"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    advice_date: Mapped[dt_date] = mapped_column(Date, nullable=False)
    
    message: Mapped[str] = mapped_column(String, nullable=False)
    flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('user_id', 'advice_date', name='uq_basal_advice_user_date'),
        {'extend_existing': True}
    )

class BasalChangeEvaluation(Base):
    __tablename__ = "basal_change_evaluation"
    __table_args__ = {'extend_existing': True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    change_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    from_dose_u: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    to_dose_u: Mapped[float] = mapped_column(Float, nullable=False)
    
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    
    result: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
