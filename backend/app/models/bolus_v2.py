from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator


class ExerciseParams(BaseModel):
    planned: bool = False
    minutes: int = Field(default=0, ge=0)
    intensity: Literal["low", "moderate", "high"] = "moderate"

    model_config = ConfigDict(allow_inf_nan=False)


class SlowMealParams(BaseModel):
    enabled: bool = False
    mode: Literal["dual", "square"] = "dual"
    upfront_pct: float = Field(default=0.6, ge=0.0, le=1.0)
    duration_min: int = Field(default=120, ge=30, le=480)

    model_config = ConfigDict(allow_inf_nan=False)


# --- Stateless Settings Models ---
class MealSlotProfile(BaseModel):
    icr: float = Field(gt=0, le=200, description="Insulin Carb Ratio (g/U)")
    isf: float = Field(gt=0, le=500, description="Insulin Sensitivity Factor (mg/dL/U)")
    target: float = Field(ge=60, le=250, description="Target Glucose (mg/dL)")
    max_bolus: float = Field(default=10.0, ge=0, le=50)

    model_config = ConfigDict(allow_inf_nan=False)


class CalcSettings(BaseModel):
    breakfast: MealSlotProfile
    lunch: MealSlotProfile
    dinner: MealSlotProfile
    snack: Optional[MealSlotProfile] = None
    dia_hours: float = Field(default=4.0, ge=2, le=8)
    insulin_model: str = "linear"
    insulin_peak_minutes: Optional[int] = Field(default=None, ge=30, le=120)
    round_step_u: float = Field(default=0.1, gt=0, le=1)
    max_bolus_u: float = Field(default=15.0, gt=0, le=50)
    max_correction_u: float = Field(default=5.0, ge=0, le=50)

    model_config = ConfigDict(allow_inf_nan=False)


class NightscoutConfigSimple(BaseModel):
    url: str
    token: Optional[str] = None


class BolusRequestV2(BaseModel):
    # Dosing inputs are deliberately bounded. Automatic CGM ingestion already
    # validates 40-400 mg/dL; manual calculation must not bypass that contract.
    carbs_g: float = Field(ge=0, le=500)
    fat_g: float = Field(default=0, ge=0, le=500)
    protein_g: float = Field(default=0, ge=0, le=500)
    fiber_g: float = Field(default=0, ge=0, le=500)
    bg_mgdl: Optional[float] = Field(default=None, ge=40, le=400)
    meal_slot: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"
    target_mgdl: Optional[float] = Field(default=None, ge=60, le=250)
    carb_profile: Optional[Literal["fast", "med", "slow"]] = None

    # Stateless configuration injection
    nightscout: Optional[NightscoutConfigSimple] = None
    settings: Optional[CalcSettings] = None

    # Flat Overrides (Hybrid mode)
    cr_g_per_u: Optional[float] = Field(default=None, gt=0, le=200)
    isf_mgdl_per_u: Optional[float] = Field(default=None, gt=0, le=500)
    dia_hours: Optional[float] = Field(default=None, ge=2, le=8)
    insulin_model: Optional[Literal["walsh", "bilinear", "fiasp", "novorapid", "linear"]] = None
    insulin_peak_minutes: Optional[int] = Field(default=None, ge=10, le=300)
    round_step_u: Optional[float] = Field(default=None, gt=0, le=1)
    max_bolus_u: Optional[float] = Field(default=None, gt=0, le=50)
    max_correction_u: Optional[float] = Field(default=None, ge=0, le=50)

    # Fiber Config Overrides
    use_fiber_deduction: Optional[bool] = Field(default=None)
    fiber_factor: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    fiber_threshold: Optional[float] = Field(default=None, ge=0.0, le=500)

    # New flags
    exercise: ExerciseParams = Field(default_factory=ExerciseParams)
    slow_meal: SlowMealParams = Field(default_factory=SlowMealParams)

    # Warsaw Overrides
    warsaw_safety_factor: Optional[float] = Field(default=None, ge=0.01, le=1.0)
    warsaw_safety_factor_dual: Optional[float] = Field(default=None, ge=0.01, le=1.0)
    warsaw_trigger_threshold_kcal: Optional[int] = Field(default=None, ge=0, le=10000)
    confirm_iob_unknown: bool = Field(default=False, description="Confirmar cálculo sin IOB disponible")
    confirm_iob_stale: bool = Field(default=False, description="Confirmar cálculo con IOB obsoleto")
    manual_iob_u: Optional[float] = Field(default=None, ge=0, le=30, description="IOB manual cuando el sistema no puede calcularlo")

    # Strategy Flags
    last_bolus_minutes: Optional[int] = Field(default=None, ge=0, description="Minutes since last insulin bolus (for safety checks)")
    alcohol: bool = Field(default=False, description="Modo Alcohol: Se asume tendencia a baja a largo plazo, suprime correcciones agresivas.")
    enable_autosens: Optional[bool] = Field(default=None, description="Optional per-request Autosens override; None uses saved user setting")

    # Strategy Override
    strategy: Literal["auto", "normal"] = "auto"

    @model_validator(mode="before")
    @classmethod
    def reject_removed_iob_bypass(cls, value):
        if isinstance(value, dict) and "ignore_iob" in value:
            raise ValueError("ignore_iob has been removed; IOB protection cannot be bypassed")
        return value

    model_config = ConfigDict(populate_by_name=True, extra="ignore", allow_inf_nan=False)


class GlucoseUsed(BaseModel):
    mgdl: Optional[float]
    source: Literal[
        "manual", "nightscout", "dexcom_share", "dexcom_android",
        "g7_direct_watch", "none"
    ]
    trend: Optional[str] = None
    age_minutes: Optional[float] = None
    is_stale: bool = False

    model_config = ConfigDict(allow_inf_nan=False)


class UsedParams(BaseModel):
    cr_g_per_u: float
    isf_mgdl_per_u: float
    target_mgdl: float
    dia_hours: float
    insulin_model: str = "linear"
    max_bolus_final: float
    isf_base: Optional[float] = None
    effective_cr_g_per_u: Optional[float] = None
    effective_isf_mgdl_per_u: Optional[float] = None
    round_step_u: Optional[float] = None
    max_correction_u: Optional[float] = None
    max_iob_u: Optional[float] = None
    min_bolus_interval_min: Optional[int] = None
    techne_enabled: Optional[bool] = None
    techne_max_step_change: Optional[float] = None
    autosens_ratio: float = 1.0
    autosens_reason: Optional[str] = None
    config_hash: Optional[str] = None

    model_config = ConfigDict(allow_inf_nan=False)


class BolusSuggestions(BaseModel):
    icr_g_per_u: Optional[float] = None
    isf_mgdl_per_u: Optional[float] = None

    model_config = ConfigDict(allow_inf_nan=False)


from app.models.iob import IOBInfo, COBInfo


class BolusResponseV2(BaseModel):
    ok: bool = True
    total_u: float = 0.0

    # Raw Calc Details
    meal_bolus_u: float
    correction_u: float
    iob_u: float
    iob_applied_to_correction_u: float = 0.0
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

    iob: Optional[IOBInfo] = None
    cob: Optional[COBInfo] = None

    clamped: bool = False
    assumptions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(allow_inf_nan=False)
