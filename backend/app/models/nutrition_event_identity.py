from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NutritionEventIdentity(Base):
    """Persisted aliases that map external nutrition events to one treatment."""

    __tablename__ = "nutrition_event_identities"
    __table_args__ = (
        Index("ix_nutrition_identity_treatment", "treatment_id"),
        Index("ix_nutrition_identity_user_source", "user_id", "source"),
    )

    identity_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    treatment_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    food_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    match_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
