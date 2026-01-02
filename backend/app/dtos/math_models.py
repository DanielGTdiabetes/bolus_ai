from dataclasses import dataclass, field
from typing import List, Optional, Literal

@dataclass
class CalculationInput:
    # Essential Params
    carbs_g: float
    target_mgdl: float
    cr: float
    isf: float
    
    # Context
    bg_mgdl: Optional[float] = None
    bg_trend: Optional[str] = None
    bg_is_stale: bool = False
    bg_age_minutes: float = 0.0
    
    # State
    iob_u: float = 0.0
    
    # Modifiers
    autosens_ratio: float = 1.0
    autosens_reason: Optional[str] = None
    
    # Flags
    alcohol_mode: bool = False
    exercise_minutes: int = 0
    exercise_intensity: str = "moderate" # low, moderate, high
    
    # Advanced Bolus
    slow_meal_enabled: bool = False
    slow_meal_upfront_pct: float = 1.0
    
    # Safety User Settings (Limits)
    max_bolus_u: float = 15.0
    max_correction_u: float = 5.0
    round_step: float = 0.1
    
@dataclass
class CalculationResult:
    total_u: float
    breakdown: List[str]
    warnings: List[str]
    
    # Components
    meal_u: float = 0.0
    corr_u: float = 0.0
    iob_devoured: float = 0.0
    
    # Split
    upfront_u: float = 0.0
    later_u: float = 0.0
    duration_min: int = 0
