from pydantic import BaseModel
from typing import Optional

class PushSubscription(BaseModel):
    endpoint: str
    keys: dict[str, str] # p256dh, auth

class NotificationSummary(BaseModel):
    has_suggestions: bool = False
    pending_suggestions_count: int = 0
    has_basal_advice: bool = False
    advice_msg: Optional[str] = None
    has_basal_change: bool = False

class MarkSeenRequest(BaseModel):
    types: list[str]
