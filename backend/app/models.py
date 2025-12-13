from datetime import datetime
from enum import Enum
from typing import Optional, Dict
from pydantic import BaseModel, Field, validator


class Role(str, Enum):
    admin = "admin"
    user = "user"


class User(BaseModel):
    username: str
    password_hash: str
    role: Role = Role.user
    created_at: datetime
    needs_password_change: bool = False


class TokenPayload(BaseModel):
    sub: str
    exp: int
    iss: str | None = None
    type: str


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class SettingsTargets(BaseModel):
    low: int = 80
    mid: int = 100
    high: int = 140


class MealRatios(BaseModel):
    breakfast: float = 1.0
    lunch: float = 1.0
    dinner: float = 1.0


class IOBSettings(BaseModel):
    dia_hours: float = 5.0
    curve: str = Field("walsh", regex="^(walsh|bilinear)$")


class LearningSchedule(BaseModel):
    enabled: bool = False
    weekday: str = "friday"
    time_local: str = Field("20:00", regex=r"^\d{2}:\d{2}$")


class LearningSettings(BaseModel):
    mode: str = Field("B", regex="^[A-Z]$")
    cr_on: bool = True
    step_pct: int = Field(5, ge=1, le=10)
    weekly_cap_pct: int = Field(15, ge=10, le=30)
    auto_apply_safe: bool = True
    schedule: LearningSchedule = LearningSchedule()


class AdaptiveFatSettings(BaseModel):
    fu: MealRatios = MealRatios()
    fl: MealRatios = MealRatios()
    delay_min: MealRatios = MealRatios()


class ExerciseRatios(BaseModel):
    walking_within90: MealRatios = MealRatios()
    walking_after90: MealRatios = MealRatios()
    cardio_within90: MealRatios = MealRatios()
    cardio_after90: MealRatios = MealRatios()
    running_within90: MealRatios = MealRatios()
    running_after90: MealRatios = MealRatios()
    gym_within90: MealRatios = MealRatios()
    gym_after90: MealRatios = MealRatios()
    other_within90: MealRatios = MealRatios()
    other_after90: MealRatios = MealRatios()


class AdaptiveSettings(BaseModel):
    fat: AdaptiveFatSettings = AdaptiveFatSettings()
    exercise: ExerciseRatios = ExerciseRatios()


class UserSettings(BaseModel):
    units: str = Field("mg/dL", regex="^(mg/dL)$")
    targets: SettingsTargets = SettingsTargets()
    cf: MealRatios = MealRatios()
    cr: MealRatios = MealRatios()
    max_bolus_u: float = Field(15, ge=0)
    max_correction_u: float = Field(10, ge=0)
    iob: IOBSettings = IOBSettings()
    learning: LearningSettings = LearningSettings()
    adaptive: AdaptiveSettings = AdaptiveSettings()

    @validator("units")
    def validate_units(cls, v: str) -> str:
        if v not in {"mg/dL"}:
            raise ValueError("Only mg/dL supported")
        return v


class ChangeSet(BaseModel):
    id: str
    timestamp: datetime
    user: str
    message: str
    diff: Dict[str, object]


class BolusRequest(BaseModel):
    carbs: float
    glucose: float
    high_fat: bool = False
    exercise_type: Optional[str] = None
    exercise_timing: Optional[str] = None


class BolusRecommendation(BaseModel):
    upfront: float
    later: float
    delay_min: int
    explanation: list[str]


class Event(BaseModel):
    id: str
    timestamp: datetime
    data: BolusRequest
    recommendation: BolusRecommendation


class SettingsResponse(BaseModel):
    settings: UserSettings
    last_modified: datetime | None = None
