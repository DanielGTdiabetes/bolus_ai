from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class TargetRange(BaseModel):
    low: int = 90
    mid: int = 100
    high: int = 120


class MealFactors(BaseModel):
    breakfast: float = 1.0
    lunch: float = 1.0
    dinner: float = 1.0


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


class UserSettings(BaseModel):
    units: Literal["mg/dL"] = "mg/dL"
    targets: TargetRange = Field(default_factory=TargetRange)
    cf: MealFactors = Field(default_factory=MealFactors)
    cr: MealFactors = Field(default_factory=MealFactors)
    max_bolus_u: float = 10.0
    max_correction_u: float = 5.0
    round_step_u: float = 0.05
    iob: IOBConfig = Field(default_factory=IOBConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    adaptive: AdaptiveConfig = Field(default_factory=AdaptiveConfig)

    @classmethod
    def migrate(cls, data: dict) -> "UserSettings":
        return cls.parse_obj(data)

    @classmethod
    def default(cls) -> "UserSettings":
        return cls()
