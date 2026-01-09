from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.db import Base

class MealEntry(Base):
    __tablename__ = "meal_entries"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Content of the meal
    items = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)  # List of detected food items names/details
    
    # Quantitative Data
    carbs_g = Column(Float, nullable=False, default=0.0)
    fat_g = Column(Float, nullable=True, default=0.0)
    protein_g = Column(Float, nullable=True, default=0.0)
    fiber_g = Column(Float, nullable=True, default=0.0)
    
    # How it was treated
    bolus_kind = Column(String, nullable=True) # "normal", "extended", "dual"
    bolus_u_total = Column(Float, nullable=True)
    bolus_u_upfront = Column(Float, nullable=True)
    bolus_u_later = Column(Float, nullable=True)
    bolus_delay_min = Column(Integer, nullable=True)
    
    # Context at time of meal
    start_bg = Column(Float, nullable=True)
    start_trend = Column(String, nullable=True)
    start_iob = Column(Float, nullable=True)

    # Validation & Replay Context
    # Stores the full prediction JSON or summary at time of bolus
    prediction_snapshot = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True) 
    # Stores the exact ICR/ISF/Abs used { "icr": 10, "isf": 100, "absorption": 180 ... }
    applied_ratios = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    
    # Outcome relationship
    outcome = relationship("MealOutcome", back_populates="meal_entry", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<MealEntry {self.id} - {self.carbs_g}g>"


class MealOutcome(Base):
    __tablename__ = "meal_outcomes"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    meal_entry_id = Column(String, ForeignKey("meal_entries.id"), nullable=False, unique=True)
    
    evaluated_at = Column(DateTime, default=datetime.utcnow)
    
    # 1-10 score. 10 = Perfect flat line. 1 = Heavy hypo or extreme hyper.
    score = Column(Integer, nullable=True)
    
    # Clinical metrics (e.g. over next 4h)
    max_bg = Column(Float, nullable=True)
    min_bg = Column(Float, nullable=True)
    final_bg = Column(Float, nullable=True) # bg at the end of the window (e.g. 4h)
    
    # Boolean flags
    hypo_occurred = Column(Boolean, default=False)
    hyper_occurred = Column(Boolean, default=False)
    
    notes = Column(Text, nullable=True)

    meal_entry = relationship("MealEntry", back_populates="outcome")

    def __repr__(self):
        return f"<MealOutcome {self.id} - Score: {self.score}>"


class ShadowLog(Base):
    __tablename__ = "shadow_logs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    meal_entry_id = Column(String, ForeignKey("meal_entries.id"), nullable=True)
    
    # Details
    meal_name = Column(String, nullable=True) # Snapshot name for UI
    scenario = Column(String, nullable=False) # e.g. "Absorción +20%"
    suggestion = Column(String, nullable=True) # Human readable text
    
    # Result comparison
    is_better = Column(Boolean, default=False)
    improvement_pct = Column(Float, nullable=True)
    
    status = Column(String, default="pending") # pending, success, neutral, failed

