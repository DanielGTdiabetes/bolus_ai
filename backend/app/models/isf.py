from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

class IsfEvent(BaseModel):
    id: str
    timestamp: datetime
    correction_units: float
    bg_start: int
    bg_end: int
    bg_delta: int
    isf_observed: float
    iob: float
    bucket: str
    valid: bool
    reason: Optional[str] = None

class IsfBucketStat(BaseModel):
    bucket: str  # "00-06", etc.
    label: str   # "Madrugada", etc.
    events_count: int
    median_isf: Optional[float]
    current_isf: float
    change_ratio: float  # e.g. 0.15 for +15%
    status: str          # "ok", "weak", "strong", "insufficient_data"
    suggestion_type: Optional[str] = None # "increase", "decrease"
    suggested_isf: Optional[float] = None
    confidence: str      # "low", "medium", "high"
    
class IsfAnalysisResponse(BaseModel):
    buckets: List[IsfBucketStat]
    clean_events: List[IsfEvent]
