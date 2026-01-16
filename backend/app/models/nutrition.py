from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from app.core.db import Base

class NutritionDraft(Base):
    __tablename__ = "nutrition_drafts"

    draft_id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    status = Column(String, default="active")
    # Store the list of food items
    items = Column(JSONB, default=list) 
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
