from typing import Literal, Optional, List
from pydantic import BaseModel, Field, model_validator
import uuid

# --- SHARED / EXISTING RE-DEFINITIONS (if needed) ---

class ManualSplit(BaseModel):
    now_u: float = Field(..., ge=0)
    later_u: float = Field(..., ge=0)
    later_after_min: int = Field(60, ge=15, le=360)

class DualSplit(BaseModel):
    percent_now: int = Field(..., ge=10, le=90)
    duration_min: int = Field(120, ge=30, le=480) 
    later_after_min: int = Field(60, ge=15, le=360) 

class BolusPlanRequest(BaseModel):
    mode: Literal["manual", "dual"]
    total_recommended_u: float = Field(..., ge=0)
    round_step_u: float = Field(0.5, gt=0)
    
    manual: Optional[ManualSplit] = None
    dual: Optional[DualSplit] = None

    @model_validator(mode='after')
    def validate_required_fields(self):
        if self.mode == "manual" and not self.manual:
            raise ValueError("Manual split details required for mode='manual'")
        if self.mode == "dual" and not self.dual:
            raise ValueError("Dual split details required for mode='dual'")
        return self


class BolusPlanResponse(BaseModel):
    plan_id: str
    mode: Literal["manual", "dual"]
    total_recommended_u: float
    now_u: float
    later_u_planned: float
    later_after_min: int
    extended_duration_min: Optional[int] = None
    warnings: List[str] = []

# --- RECALC SECOND ---

class BolusParams(BaseModel):
    cr_g_per_u: float = Field(..., gt=0)
    isf_mgdl_per_u: float = Field(..., gt=0)
    target_bg_mgdl: float = Field(..., gt=0)
    round_step_u: float = Field(0.5, gt=0)
    max_bolus_u: float = Field(20.0, gt=0)
    stale_bg_minutes: int = Field(15, gt=0)

class NightscoutConn(BaseModel):
    url: str
    token: Optional[str] = None
    units: Optional[Literal["mgdl", "mmol"]] = "mgdl"

class RecalcSecondRequest(BaseModel):
    later_u_planned: float = Field(..., ge=0)
    carbs_additional_g: float = Field(0, ge=0)
    params: BolusParams
    nightscout: NightscoutConn

class RecalcComponents(BaseModel):
    meal_u: float
    correction_u: float
    iob_applied_u: float

class RecalcSecondResponse(BaseModel):
    bg_now_mgdl: Optional[float] = None
    bg_age_min: Optional[int] = None
    iob_now_u: Optional[float] = None
    components: RecalcComponents
    cap_u: float
    u2_recommended_u: float
    warnings: List[str] = []
