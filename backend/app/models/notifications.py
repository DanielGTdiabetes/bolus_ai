
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import String, DateTime, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

class UserNotificationState(Base):
    __tablename__ = "user_notification_state"
    __table_args__ = (
        UniqueConstraint('user_id', 'key', name='uq_user_notif_state_key'),
        {'extend_existing': True}
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    key: Mapped[str] = mapped_column(String, nullable=False)
    # Key examples: 'suggestion_pending', 'evaluation_ready', 'basal_review_2025-01-01'
    
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint('user_id', 'endpoint', name='uq_push_user_endpoint'),
        {'extend_existing': True}
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    keys: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
