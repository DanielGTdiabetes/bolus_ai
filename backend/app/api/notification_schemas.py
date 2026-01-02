from pydantic import BaseModel, Field


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict[str, str]  # p256dh, auth


class NotificationItem(BaseModel):
    type: str
    title: str
    message: str
    route: str
    count: int = 0
    unread: bool = False
    priority: str


class NotificationSummary(BaseModel):
    has_unread: bool = False
    items: list[NotificationItem] = Field(default_factory=list)


class MarkSeenRequest(BaseModel):
    types: list[str]
