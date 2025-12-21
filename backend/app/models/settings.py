from __future__ import annotations

from typing import Literal, Optional
from datetime import datetime

from pydantic import BaseModel, Field


class TargetRange(BaseModel):
    low: int = 90
    mid: int = 100
    high: int = 120


class MealFactors(BaseModel):
    # Default CR to 10.0 g/U (safer than 1.0)
    breakfast: float = Field(default=10.0, description="Ratio CR (g/U)")
    lunch: float = Field(default=10.0, description="Ratio CR (g/U)")
    dinner: float = Field(default=10.0, description="Ratio CR (g/U)")
    snack: float = Field(default=10.0, description="Ratio CR (g/U)")


class AdaptiveFatConfig(BaseModel):
    fu: float = 1.0
    fl: float = 1.0
    delay_min: int = 0


class AdaptiveExerciseConfig(BaseModel):
    within90: float = 1.0
    after90: float = 1.0


class ExerciseRatios(BaseModel):
    walking: AdaptiveExerciseConfig = Field(default_factory=AdaptiveExerciseConfig)
    cardio: AdaptiveExerciseConfig = Field(default_factory=AdaptiveExerciseConfig)
    running: AdaptiveExerciseConfig = Field(default_factory=AdaptiveExerciseConfig)
    gym: AdaptiveExerciseConfig = Field(default_factory=AdaptiveExerciseConfig)
    other: AdaptiveExerciseConfig = Field(default_factory=AdaptiveExerciseConfig)


class AdaptiveConfig(BaseModel):
    fat: dict[str, AdaptiveFatConfig] = Field(
        default_factory=lambda: {
            "breakfast": AdaptiveFatConfig(),
            "lunch": AdaptiveFatConfig(),
            "dinner": AdaptiveFatConfig(),
        }
    )
    exercise: dict[str, ExerciseRatios] = Field(
        default_factory=lambda: {
            "breakfast": ExerciseRatios(),
            "lunch": ExerciseRatios(),
            "dinner": ExerciseRatios(),
        }
    )


class LearningSchedule(BaseModel):
    enabled: bool = False
    weekday: str = "friday"
    time_local: str = "20:00"


class LearningConfig(BaseModel):
    mode: Literal["B"] = "B"
    cr_on: bool = True
    step_pct: int = Field(default=5, ge=1, le=10)
    weekly_cap_pct: int = Field(default=20, ge=10, le=30)
    auto_apply_safe: bool = True
    schedule: LearningSchedule = Field(default_factory=LearningSchedule)


class IOBConfig(BaseModel):
    dia_hours: float = Field(default=4.0, gt=0)
    curve: Literal["walsh", "bilinear"] = "walsh"
    peak_minutes: int = Field(default=75, ge=10, le=300)


class NightscoutConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    token: Optional[str] = None
    units: Literal["mg/dl", "mmol/l"] = "mg/dl"


class TechneRoundingConfig(BaseModel):
    enabled: bool = False
    max_step_change: float = 0.5  # Safety limit: never deviate > 0.5U from raw
    safety_iob_threshold: float = 1.5  # If IOB > this, disable Techne rounding (avoid stacking)


class VisionConfig(BaseModel):
    provider: Literal["gemini", "openai"] = "gemini"
    
    # Gemini Config
    gemini_key: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash-exp" # Default recommended
    
    # OpenAI Config
    openai_key: Optional[str] = None
    openai_model: str = "gpt-4o"



class UserSettings(BaseModel):
    schema_version: int = 1
    units: Literal["mg/dL"] = "mg/dL"
    targets: TargetRange = Field(default_factory=TargetRange)
    cf: MealFactors = Field(default_factory=lambda: MealFactors(breakfast=30, lunch=30, dinner=30, snack=30)) # Default CF 30
    cr: MealFactors = Field(default_factory=MealFactors)
    max_bolus_u: float = 10.0
    max_correction_u: float = 5.0
    round_step_u: float = 0.05
    tdd_u: Optional[float] = Field(default=None, ge=1.0, description="Total Daily Dose typical (U)")
    iob: IOBConfig = Field(default_factory=IOBConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    adaptive: AdaptiveConfig = Field(default_factory=AdaptiveConfig)
    nightscout: NightscoutConfig = Field(default_factory=NightscoutConfig)
class InsulinSettings(BaseModel):
    name: str = Field(default="Novorapid", description="Name of the insulin used")
    sensor_delay_min: int = Field(default=15, description="Delay in minutes for glucose sensor readings")
    pre_bolus_min: int = Field(default=15, description="Recommended wait time before eating after bolus")


class UserSettings(BaseModel):
    schema_version: int = 1
    units: Literal["mg/dL"] = "mg/dL"
    targets: TargetRange = Field(default_factory=TargetRange)
    cf: MealFactors = Field(default_factory=lambda: MealFactors(breakfast=30, lunch=30, dinner=30, snack=30)) # Default CF 30
    cr: MealFactors = Field(default_factory=MealFactors)
    max_bolus_u: float = 10.0
    max_correction_u: float = 5.0
    round_step_u: float = 0.05
    tdd_u: Optional[float] = Field(default=None, ge=1.0, description="Total Daily Dose typical (U)")
    iob: IOBConfig = Field(default_factory=IOBConfig)
    insulin: InsulinSettings = Field(default_factory=InsulinSettings)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    adaptive: AdaptiveConfig = Field(default_factory=AdaptiveConfig)
    nightscout: NightscoutConfig = Field(default_factory=NightscoutConfig)
    techne: TechneRoundingConfig = Field(default_factory=TechneRoundingConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    
    # Internal field to track update time from DB, not part of user input JSON usually
    updated_at: Optional[datetime] = None

    @classmethod
    def migrate(cls, data: dict) -> "UserSettings":
        # 1. Frontend Legacy Format Support (Grouped by Slot)
        # Frontend sends: { "lunch": { "icr": 10, "isf": 50 }, ... }
        # Backend expects: { "cr": { "lunch": 10 }, "cf": { "lunch": 50 } }
        
        # Detect legacy format by checking for common slots
        if "lunch" in data and isinstance(data["lunch"], dict) and ("icr" in data["lunch"] or "isf" in data["lunch"]):
            new_cr = data.get("cr", {})
            new_cf = data.get("cf", {})
            
            # Normalize to dicts if they are objects/models
            if hasattr(new_cr, "model_dump"): new_cr = new_cr.model_dump()
            if hasattr(new_cf, "model_dump"): new_cf = new_cf.model_dump()
            if not isinstance(new_cr, dict): new_cr = {}
            if not isinstance(new_cf, dict): new_cf = {}

            # Map slots
            for slot in ["breakfast", "lunch", "dinner", "snack"]:
                if slot in data and isinstance(data[slot], dict):
                    # Map ICR -> CR
                    if "icr" in data[slot]:
                        try:
                            val = float(data[slot]["icr"])
                            if val > 0: new_cr[slot] = val
                        except: pass
                    
                    # Map ISF -> CF
                    if "isf" in data[slot]:
                        try:
                            val = float(data[slot]["isf"])
                            if val > 0: new_cf[slot] = val
                        except: pass
            
            data["cr"] = new_cr
            data["cf"] = new_cf


        # 2. Logic Correction: Detect inverted CR or unsafe defaults
        cr_data = data.get("cr", {})
        # If cr_data is a dict (it should be now), iterate keys
        if isinstance(cr_data, dict):
            for slot in ["breakfast", "lunch", "dinner", "snack"]:
                val = float(cr_data.get(slot, 0))
                if 0 < val < 2.0:
                    # Inverted logic detected? Or just unsafe default.
                    # Convert: new = 1 / val? 
                    # If val=1.0 (old default), 1/1=1. No change.
                    # If val=0.1 (user entered 0.1 U/g), 1/0.1=10. Good.
                    new_val = 1.0 / val
                    if new_val >= 2.0:
                        cr_data[slot] = round(new_val, 1)
                    else:
                        # If flipping doesn't help (e.g. 1.0 -> 1.0), force default safety?
                        if val == 1.0:
                             cr_data[slot] = 10.0
            data["cr"] = cr_data
            
        return cls.model_validate(data)

    @classmethod
    def default(cls) -> "UserSettings":
        return cls()


# --- SQL Model ---
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import Base

class UserSettingsDB(Base):
    __tablename__ = "user_settings"
    __table_args__ = {'extend_existing': True}

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    
    # Stores the JSON blob validated by UserSettings Pydantic model
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
