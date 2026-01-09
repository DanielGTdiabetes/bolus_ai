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
    snack: Optional[MealSlotProfile] = None
    dia_hours: float = Field(default=4.0, ge=2, le=8)
    insulin_model: str = "linear" # Added
    round_step_u: float = Field(default=0.1, gt=0)
    max_bolus_u: float = 15.0 # Global safety limit
    max_correction_u: float = 5.0 # Global safety limit

class NightscoutConfigSimple(BaseModel):
    url: str
    token: Optional[str] = None

class BolusRequestV2(BaseModel):
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(default=0, ge=0)
    protein_g: float = Field(default=0, ge=0)
    fiber_g: float = Field(default=0, ge=0)
    bg_mgdl: Optional[float] = Field(default=None, ge=0)
    meal_slot: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"
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

    # Fiber Config Overrides
    use_fiber_deduction: Optional[bool] = Field(default=None)
    fiber_factor: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    fiber_threshold: Optional[float] = Field(default=None, ge=0.0)

    # New flags
    exercise: ExerciseParams = Field(default_factory=ExerciseParams)
    slow_meal: SlowMealParams = Field(default_factory=SlowMealParams)
    
    # Warsaw Overrides
    warsaw_safety_factor: Optional[float] = Field(default=None, ge=0.01, le=1.0)
    warsaw_safety_factor_dual: Optional[float] = Field(default=None, ge=0.01, le=1.0)
    warsaw_trigger_threshold_kcal: Optional[int] = Field(default=None, ge=0)
    confirm_iob_unknown: bool = Field(default=False, description="Confirmar cálculo sin IOB disponible")
    confirm_iob_stale: bool = Field(default=False, description="Confirmar cálculo con IOB obsoleto")
    
    # Strategy Flags
    ignore_iob: bool = Field(default=False, description="Modo Comida Grasa: Ignorar IOB para calcular corrección (Micro-bolos reactivos)")
    last_bolus_minutes: Optional[int] = Field(default=None, description="Minutes since last insulin bolus (for safety checks)")
    alcohol: bool = Field(default=False, description="Modo Alcohol: Se asume tendencia a baja a largo plazo, suprime correcciones agresivas.")
    enable_autosens: bool = Field(default=True, description="Enable Autosens (Dynamic ISF/ICR)")

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
    insulin_model: str = "linear" # Added
    max_bolus_final: float
    isf_base: Optional[float] = None
    autosens_ratio: float = 1.0
    autosens_reason: Optional[str] = None
    config_hash: Optional[str] = None


class BolusSuggestions(BaseModel):
    icr_g_per_u: Optional[float] = None
    isf_mgdl_per_u: Optional[float] = None


from app.models.iob import IOBInfo, COBInfo

class BolusResponseV2(BaseModel):
    ok: bool = True
    total_u: float = 0.0 # Renamed for clarity but keeping total_u as alias if needed
    
    # Raw Calc Details
    meal_bolus_u: float
    correction_u: float
    iob_u: float
    total_u_raw: float
    total_u_final: float
    
    kind: Literal["normal", "extended", "dual"]
    upfront_u: float
    later_u: float
    duration_min: int = 0
    
    glucose: GlucoseUsed
    used_params: UsedParams
    suggestions: BolusSuggestions = Field(default_factory=BolusSuggestions)
    
    explain: list[str]
    warnings: list[str] = []
    
    iob: Optional[IOBInfo] = None # Correctly typed to avoid warnings
    cob: Optional[COBInfo] = None
    
    clamped: bool = False
    assumptions: list[str] = Field(default_factory=list)
