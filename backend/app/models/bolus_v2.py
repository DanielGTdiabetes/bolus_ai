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


# --- Stateless Settings Models ---
class MealSlotProfile(BaseModel):
    icr: float = Field(gt=0, description="Insulin Carb Ratio (g/U)")
    isf: float = Field(gt=0, description="Insulin Sensitivity Factor (mg/dL/U)")
    target: float = Field(ge=60, description="Target Glucose (mg/dL)")
    max_bolus: float = Field(default=10.0, ge=0)

class CalcSettings(BaseModel):
    breakfast: MealSlotProfile
    lunch: MealSlotProfile
    dinner: MealSlotProfile
    dia_hours: float = Field(default=4.0, ge=2, le=8)
    round_step_u: float = Field(default=0.1, gt=0)
    max_bolus_u: float = 15.0 # Global safety limit
    max_correction_u: float = 5.0 # Global safety limit

class NightscoutConfigSimple(BaseModel):
    url: str
    token: Optional[str] = None

class BolusRequestV2(BaseModel):
    carbs_g: float = Field(ge=0)
    bg_mgdl: Optional[float] = Field(default=None, ge=0)
    meal_slot: Literal["breakfast", "lunch", "dinner"] = "lunch"
    target_mgdl: Optional[float] = Field(default=None, ge=60)
    
    # Stateless configuration injection
    nightscout: Optional[NightscoutConfigSimple] = None
    settings: Optional[CalcSettings] = None

    # Flat Overrides (Hybrid mode)
    cr_g_per_u: Optional[float] = Field(default=None, gt=0)
    isf_mgdl_per_u: Optional[float] = Field(default=None, gt=0)
    dia_hours: Optional[float] = Field(default=None, ge=2, le=8)
    round_step_u: Optional[float] = Field(default=None, gt=0)
    max_bolus_u: Optional[float] = Field(default=None, gt=0)
    max_correction_u: Optional[float] = Field(default=None, gt=0)

    # New flags
    exercise: ExerciseParams = Field(default_factory=ExerciseParams)
    slow_meal: SlowMealParams = Field(default_factory=SlowMealParams)
    ignore_iob_for_meal: bool = Field(default=False, description="Techne: If true, IOB is only subtracted from correction, not meal.")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GlucoseUsed(BaseModel):
    mgdl: Optional[float]
    source: Literal["manual", "nightscout", "none"]
    trend: Optional[str] = None
    age_minutes: Optional[float] = None 
    is_stale: bool = False           


class UsedParams(BaseModel):
    cr_g_per_u: float
    isf_mgdl_per_u: float
    target_mgdl: float
    dia_hours: float
    max_bolus_final: float


class BolusSuggestions(BaseModel):
    icr_g_per_u: Optional[float] = None
    isf_mgdl_per_u: Optional[float] = None


from app.models.iob import IOBInfo

class BolusResponseV2(BaseModel):
    ok: bool = True
    total_u: float = 0.0 # Renamed for clarity but keeping total_u as alias if needed
    
    # Raw Calc Details
    meal_bolus_u: float
    correction_u: float
    iob_u: float
    total_u_raw: float
    total_u_final: float
    
    kind: Literal["normal", "extended"]
    upfront_u: float
    later_u: float
    duration_min: int = 0
    
    glucose: GlucoseUsed
    used_params: UsedParams
    suggestions: BolusSuggestions = Field(default_factory=BolusSuggestions)
    
    explain: list[str]
    warnings: list[str] = []
    
    iob: Optional[IOBInfo] = None # Correctly typed to avoid warnings
    
    clamped: bool = False

