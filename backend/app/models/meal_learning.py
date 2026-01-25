from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.core.db import Base


class MealExperience(Base):
    __tablename__ = "meal_experiences"
    __table_args__ = (
        UniqueConstraint("user_id", "treatment_id", name="uq_meal_experiences_user_treatment"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    treatment_id = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)

    meal_type = Column(String, nullable=True)
    carbs_g = Column(Float, nullable=False, default=0.0)
    protein_g = Column(Float, nullable=False, default=0.0)
    fat_g = Column(Float, nullable=False, default=0.0)
    fiber_g = Column(Float, nullable=False, default=0.0)
    tags_json = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)

    carb_profile = Column(String, nullable=True)
    event_kind = Column(String, nullable=False)
    window_status = Column(String, nullable=False)
    discard_reason = Column(Text, nullable=True)

    bg_start = Column(Float, nullable=True)
    bg_peak = Column(Float, nullable=True)
    bg_min = Column(Float, nullable=True)
    bg_end_2h = Column(Float, nullable=True)
    bg_end_3h = Column(Float, nullable=True)
    bg_end_5h = Column(Float, nullable=True)
    delta_2h = Column(Float, nullable=True)
    delta_3h = Column(Float, nullable=True)
    delta_5h = Column(Float, nullable=True)
    score = Column(Float, nullable=True)

    event_kind_reason = Column(Text, nullable=True)
    data_quality_json = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)


class MealCluster(Base):
    __tablename__ = "meal_clusters"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    cluster_key = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    carb_profile = Column(String, nullable=True)
    tags_key = Column(String, nullable=True)

    centroid_carbs = Column(Float, nullable=False, default=0.0)
    centroid_protein = Column(Float, nullable=False, default=0.0)
    centroid_fat = Column(Float, nullable=False, default=0.0)
    centroid_fiber = Column(Float, nullable=False, default=0.0)

    n_ok = Column(Integer, nullable=False, default=0)
    n_discarded = Column(Integer, nullable=False, default=0)
    confidence = Column(String, nullable=False, default="low")

    absorption_duration_min = Column(Integer, nullable=True)
    peak_min = Column(Integer, nullable=True)
    tail_min = Column(Integer, nullable=True)
    shape = Column(String, nullable=True, default="triangle")
    last_updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
