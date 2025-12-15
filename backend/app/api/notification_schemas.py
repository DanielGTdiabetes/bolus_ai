
from typing import List
from pydantic import BaseModel

class NotificationItem(BaseModel):
    type: str # suggestion_pending | evaluation_ready | basal_review_today
    count: int
    title: str
    message: str
    route: str

class NotificationSummary(BaseModel):
    has_unread: bool
    items: List[NotificationItem]

class MarkSeenRequest(BaseModel):
    types: List[str]
