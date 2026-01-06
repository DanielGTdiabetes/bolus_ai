from datetime import datetime
from typing import Optional, Literal, List
from pydantic import BaseModel

IOBStatus = Literal["ok", "unavailable", "partial", "stale"]
COBStatus = Literal["ok", "unavailable", "partial", "stale"]


class SourceStatus(BaseModel):
    source: str = "unknown"
    status: Literal["ok", "error", "unavailable", "stale", "unknown"] = "unknown"
    reason: Optional[str] = None
    fetched_at: Optional[datetime] = None


class IOBInfo(BaseModel):
    iob_u: Optional[float] = None
    status: IOBStatus = "unavailable"
    reason: Optional[str] = None
    source: str = "unknown"
    fetched_at: datetime
    last_known_iob: Optional[float] = None
    last_updated_at: Optional[datetime] = None
    treatments_source_status: Optional[SourceStatus] = None
    glucose_source_status: Optional[SourceStatus] = None
    assumptions: List[str] = []


class COBInfo(BaseModel):
    cob_g: Optional[float] = None
    status: COBStatus = "unavailable"
    model: str = "linear"
    assumptions: List[str] = []
    source: str = "unknown"
    reason: Optional[str] = None
    fetched_at: datetime
