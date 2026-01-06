from datetime import datetime
from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
import uuid

class TempModeDB(Base):
    __tablename__ = "temp_modes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, index=True)
    mode: Mapped[str] = mapped_column(String, nullable=False) # alcohol, exercise, etc.
    
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    
    note: Mapped[str] = mapped_column(Text, nullable=True)
