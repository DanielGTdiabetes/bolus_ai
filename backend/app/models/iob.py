from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel

IOBStatus = Literal["ok", "unavailable", "partial"]

class IOBInfo(BaseModel):
    iob_u: Optional[float] = None
    status: IOBStatus = "unavailable"
    reason: Optional[str] = None
    source: str = "unknown"
    fetched_at: datetime
