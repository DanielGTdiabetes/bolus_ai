from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _to_epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class NightscoutStatus(BaseModel):
    status: Optional[str] = None
    version: Optional[str] = None
    api_enabled: Optional[bool] = Field(default=None, alias="apiEnabled")


class NightscoutSGV(BaseModel):
    sgv: int
    direction: Optional[str]
    date: int
    delta: Optional[float] = None

    @field_validator("date", mode="before")
    def ensure_epoch_ms(cls, v: int | datetime) -> int:
        if isinstance(v, datetime):
            return _to_epoch_ms(v)
        return int(v)


class Treatment(BaseModel):
    eventType: Optional[str] = None
    created_at: Optional[datetime] = None
    enteredBy: Optional[str] = None
    insulin: Optional[float] = None
    carbs: Optional[float] = None
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FullHealth(BaseModel):
    ok: bool
    uptime_seconds: float
    version: str
    nightscout: dict
    server: dict
