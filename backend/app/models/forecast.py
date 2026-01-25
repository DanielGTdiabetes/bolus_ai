from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator

# --- Sub-models ---

class MomentumConfig(BaseModel):
    enabled: bool = True
    lookback_points: int = 3 # Number of recent BG points to use for slope calculation

class SimulationParams(BaseModel):
    isf: float = Field(..., description="Insulin Sensitivity Factor (mg/dL / U)")
    icr: float = Field(..., description="Insulin Carb Ratio (g / U)")
    dia_minutes: int = Field(360, description="Duration of Insulin Action in minutes")
    carb_absorption_minutes: int = Field(180, description="Duration of Carb Absorption in minutes")
    insulin_peak_minutes: int = Field(75, description="Peak activity time of insulin (e.g. 75 for Rapid, 55 for Fiasp)")
    insulin_onset_minutes: Optional[int] = Field(None, description="Delay before insulin starts acting (physiological onset). None = Auto-detect.")
    insulin_model: str = Field("linear", description="Type of insulin model: 'linear', 'exponential', 'fiasp', 'novorapid'")
    insulin_sensitivity_multiplier: Optional[float] = Field(None, description="Global multiplier for insulin efficacy (<1.0 = resistance)")
    basal_daily_units: float = Field(0.0, description="Users typical daily basal dose for reference. If 0, assumes current active is correct.")
    
    # User Preferences
    warsaw_factor_simple: Optional[float] = Field(None, description="Kcal to Carbs conversion factor for Simple Mode (def: None = use User Settings or 1.0)")
    warsaw_trigger: Optional[int] = Field(None, description="Kcal trigger for Dual Mode (def: None = use User Settings)")

    # Fiber Preferences
    use_fiber_deduction: bool = Field(False, description="Subtract fiber from total carbs")
    fiber_factor: float = Field(0.0, description="Multiplier for fiber deduction (e.g. 0.5 = subtract 50% of fiber)")
    fiber_threshold: float = Field(5.0, description="Minimum fiber grams to trigger deduction")
    
    target_bg: float = Field(100.0, description="User's target BG (mid) for correction calculations")

    @field_validator("warsaw_factor_simple")
    def _validate_warsaw(cls, v: Optional[float]) -> Optional[float]:
        if v is None or v <= 0:
            return 0.1
        return v
    
class ForecastEventBolus(BaseModel):
    time_offset_min: int = Field(0, description="Minutes from now (0=now, negative=past)")
    units: float
    duration_minutes: float = Field(0.0, description="Duration in minutes (0=instant)")

class ForecastEventCarbs(BaseModel):
    time_offset_min: int = Field(0, description="Minutes from now (0=now, negative=past)")
    grams: float
    fiber_g: float = 0.0
    fat_g: float = 0.0
    protein_g: float = 0.0
    absorption_minutes: Optional[int] = None # Override global absorption if set
    icr: Optional[float] = None # Specific ICR for this meal (g/U)
    carb_profile: Optional[str] = None # 'fast', 'med', 'slow' or None (auto)
    is_dessert: bool = False # Flag for dessert mode (forces fast absorption)

class ForecastBasalInjection(BaseModel):
    time_offset_min: int = Field(0, description="Minutes from now (transaction time)")
    units: float
    type: Literal["glargine", "detemir", "degludec", "nph", "custom"] = "glargine"
    duration_minutes: Optional[int] = None # Required if custom, or to override defaults

class ForecastEvents(BaseModel):
    boluses: List[ForecastEventBolus] = []
    carbs: List[ForecastEventCarbs] = []
    basal_injections: List[ForecastBasalInjection] = []

# --- Request ---

class ForecastSimulateRequest(BaseModel):
    start_bg: float = Field(..., description="Current Blood Glucose in mg/dL")
    units: Literal["mgdl", "mmol"] = "mgdl"
    horizon_minutes: int = Field(240, description="How far ahead to predict")
    step_minutes: int = Field(5, description="Granularity of the prediction series")
    
    momentum: Optional[MomentumConfig] = None
    params: SimulationParams
    events: ForecastEvents = Field(default_factory=ForecastEvents)
    
    # Context (Recent Data) for Momentum
    # Provide simple arrays if not doing full DB lookup here
    # t=0 is now, t=-5 is 5 min ago.
    recent_bg_series: Optional[List[dict]] = Field(
        None, 
        description="Optional list of recent BG [{'minutes_ago': 0, 'value': 120}, ...]"
    )

# --- Response ---

class ForecastPoint(BaseModel):
    t_min: int
    bg: float
    
class ComponentImpact(BaseModel):
    t_min: int
    insulin_impact: float = 0.0 # Negative usually
    carb_impact: float = 0.0 # Positive usually
    basal_impact: float = 0.0 # Negative usually
    momentum_impact: float = 0.0 # Variable

class ForecastSummary(BaseModel):
    bg_now: float
    bg_30m: Optional[float] = None
    bg_2h: Optional[float] = None
    bg_4h: Optional[float] = None
    min_bg: float
    max_bg: float
    time_to_min: Optional[int] = None # Minutes until lowest point
    ending_bg: float

class NightPatternMeta(BaseModel):
    enabled: bool = False
    applied: bool = False
    window: Optional[Literal["A", "B"]] = None
    reason_not_applied: Optional[str] = None
    weight: Optional[float] = None
    cap_mgdl: Optional[float] = None
    sample_days: Optional[int] = None
    sample_points: Optional[int] = None
    dispersion: Optional[float] = None
    computed_at: Optional[datetime] = None


class PredictionMeta(BaseModel):
    pattern: NightPatternMeta = Field(default_factory=NightPatternMeta)

class ForecastResponse(BaseModel):
    series: List[ForecastPoint]
    baseline_series: Optional[List[ForecastPoint]] = None # Comparison series (e.g., without future bolus)
    components: Optional[List[ComponentImpact]] = None

    summary: ForecastSummary
    
    quality: Literal["high", "medium", "low"] = "high"
    warnings: List[str] = []
    
    # NEW: Absorption Profile Feedback
    absorption_profile_used: Optional[str] = None # 'fast', 'med', 'slow', 'none'
    absorption_confidence: Literal["high", "medium", "low"] = "medium"
    absorption_reasons: List[str] = []

    slow_absorption_active: bool = False # Flag for Visual Feedback (Comida Grasa / Dual)
    slow_absorption_reason: Optional[str] = None # Reason for slow mode (e.g. Alcohol, Dual Bolus)

    # ML Inference Real
    ml_series: Optional[List[ForecastPoint]] = None # Previously List[dict], now preferred ForecastPoint (p50)
    p10_series: Optional[List[ForecastPoint]] = None
    p90_series: Optional[List[ForecastPoint]] = None
    ml_ready: bool = False 
    confidence_score: Optional[float] = None
    
    prediction_meta: Optional[PredictionMeta] = None
    meta: Optional[dict] = None

