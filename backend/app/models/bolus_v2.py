from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


class ExerciseParams(BaseModel):
    planned: bool = False
    minutes: int = Field(default=0, ge=0)
    intensity: Literal["low", "moderate", "high"] = "moderate"


class SlowMealParams(BaseModel):
    enabled: bool = False
    mode: Literal["dual", "square"] = "dual"
    upfront_pct: float = Field(default=0.6, ge=0.0, le=1.0)
    duration_min: int = Field(default=120, ge=30, le=480)


class BolusRequestV2(BaseModel):
    carbs_g: float = Field(ge=0)
    bg_mgdl: Optional[float] = Field(default=None, ge=0)
    meal_slot: Literal["breakfast", "lunch", "dinner"] = "lunch"
    target_mgdl: Optional[float] = Field(default=None, ge=60)
    # New flags
    exercise: ExerciseParams = Field(default_factory=ExerciseParams)
    slow_meal: SlowMealParams = Field(default_factory=SlowMealParams)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GlucoseUsed(BaseModel):
    mgdl: Optional[float]
    source: Literal["manual", "nightscout", "none"]
    trend: Optional[str] = None


class UsedParams(BaseModel):
    cr_g_per_u: float
    isf_mgdl_per_u: float
    target_mgdl: float
    dia_hours: float


class BolusSuggestions(BaseModel):
    icr_g_per_u: Optional[float] = None
    isf_mgdl_per_u: Optional[float] = None


class BolusResponseV2(BaseModel):
    total_u: float
    kind: Literal["normal", "extended"]
    upfront_u: float
    later_u: float
    duration_min: int = 0
    iob_u: float
    
    glucose: GlucoseUsed
    used_params: UsedParams
    suggestions: BolusSuggestions = Field(default_factory=BolusSuggestions)
    
    explain: list[str]
    warnings: list[str] = []
