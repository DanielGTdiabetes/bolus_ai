
from datetime import datetime, timezone
import uuid
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

class NightscoutSecrets(Base):
    __tablename__ = "nightscout_secrets"

    user_id: Mapped[str] = mapped_column(String, primary_key=True) # Text based ID (username) as per request
    ns_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
