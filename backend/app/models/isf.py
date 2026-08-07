from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from pydantic import Field

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
    quality_ok: bool = True
    reason_flags: List[str] = Field(default_factory=list)

class IsfBucketStat(BaseModel):
    bucket: str  # "00-06", etc.
    label: str   # "Madrugada", etc.
    events_count: int
    median_isf: Optional[float]
    observed_range: Optional[tuple[float, float]] = None
    current_isf: float
    change_ratio: float  # e.g. 0.15 for +15%
    status: str          # "ok", "weak", "strong", "insufficient_data"
    suggestion_type: Optional[str] = None # "increase", "decrease"
    suggested_isf: Optional[float] = None
    confidence: str      # "low", "medium", "high"

class IsfRunSummary(BaseModel):
    timestamp: datetime
    days: int
    n_events: int
    recommendation: Optional[str] = None
    diff_percent: Optional[float] = None
    flags: List[str] = Field(default_factory=list)
    
class IsfAnalysisResponse(BaseModel):
    buckets: List[IsfBucketStat]
    clean_events: List[IsfEvent]
    blocked_recent_hypo: bool = False
    global_reason_flags: List[str] = Field(default_factory=list)
    runs: List[IsfRunSummary] = Field(default_factory=list)
    discarded_events_count: int = 0
    discarded_reasons: dict[str, int] = Field(default_factory=dict)
    methodology: str = "correction_only_dia_window"
    auto_change_allowed: bool = False
