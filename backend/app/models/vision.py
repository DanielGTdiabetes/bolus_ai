from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.models.schemas import NightscoutSGV


class FoodItemEstimate(BaseModel):
    name: str
    carbs_g: float
    notes: Optional[str] = None


class UserInputQuestion(BaseModel):
    id: str
    question: str
    options: list[str]


class GlucoseUsed(BaseModel):
    mgdl: Optional[int]
    trend: Optional[str] = None
    source: Literal["nightscout", "manual"] | None = None


class VisionBolusRecommendation(BaseModel):
    upfront_u: float
    later_u: float
    delay_min: Optional[int]
    iob_u: float
    explain: list[str]
    kind: Literal["normal", "extended"]


class VisionEstimateResponse(BaseModel):
    carbs_estimate_g: float
    carbs_range_g: tuple[float, float]
    confidence: Literal["low", "medium", "high"]
    items: list[FoodItemEstimate]
    fat_score: float = Field(ge=0.0, le=1.0)
    slow_absorption_score: float = Field(ge=0.0, le=1.0)
    assumptions: list[str]
    needs_user_input: list[UserInputQuestion]
    glucose_used: GlucoseUsed
    bolus: Optional[VisionBolusRecommendation] = None
    
    # Internal usage or debugging
    raw_analysis: Optional[str] = None


class VisionEstimateRequest(BaseModel):
    meal_slot: Optional[Literal["breakfast", "lunch", "dinner"]] = "lunch"
    bg_mgdl: Optional[int] = None
    target_mgdl: Optional[int] = None
    portion_hint: Optional[Literal["small", "medium", "large"]] = None
    prefer_extended: bool = True
