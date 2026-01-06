from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class InjectionState(Base):
    __tablename__ = "injection_states"
    # Composite PK: user_id + plan (bolus/basal)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    plan: Mapped[str] = mapped_column(String, primary_key=True)  # "bolus" or "basal"
    
    last_used_id: Mapped[str] = mapped_column(String, nullable=False)
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
