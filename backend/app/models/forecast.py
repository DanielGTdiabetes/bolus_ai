from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

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
    insulin_model: str = Field("linear", description="Type of insulin model: 'linear', 'exponential', 'fiasp', 'novorapid'")
    
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
    horizon_minutes: int = Field(360, description="How far ahead to predict")
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

class ForecastResponse(BaseModel):
    series: List[ForecastPoint]
    baseline_series: Optional[List[ForecastPoint]] = None # Comparison series (e.g., without future bolus)
    components: Optional[List[ComponentImpact]] = None
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
