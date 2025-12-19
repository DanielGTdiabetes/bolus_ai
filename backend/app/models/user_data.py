
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class FavoriteFood(Base):
    __tablename__ = "favorite_foods"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    carbs: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class SupplyItem(Base):
    __tablename__ = "supply_items"
    
    # We use a composite key logical approach, but SQLAlchamy usually wants a PK.
    # We can use an ID or make the constraint unique. 
    # Let's use a synthetic ID but enforce unique (user_id, item_key).
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    item_key: Mapped[str] = mapped_column(String, nullable=False) # e.g. "supplies_needles"
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "item_key", name="uq_user_supply_item"),
    )
