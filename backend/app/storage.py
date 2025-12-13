import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Tuple
from uuid import uuid4
from passlib.context import CryptContext
from jose import jwt

from .config import get_settings
from .models import UserSettings, User, ChangeSet, Event, BolusRecommendation, BolusRequest

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class JsonStore:
    def __init__(self, filename: str):
        settings = get_settings()
        self.path = Path(settings.data_dir) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self, default):
        if not self.path.exists():
            self.save(default)
            return default
        try:
            with self.path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            self.save(default)
            return default

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)


user_store = JsonStore("users.json")
session_store = JsonStore("sessions.json")
settings_store = JsonStore("settings.json")
changes_store = JsonStore("changes.json")
events_store = JsonStore("events.json")


def ensure_default_admin():
    data = user_store.load([])
    if not data:
        default_user = User(
            username="admin",
            password_hash=pwd_context.hash("admin123"),
            role="admin",
            created_at=datetime.now(timezone.utc),
            needs_password_change=True,
        )
        user_store.save([default_user.dict()])
        return default_user
    return User(**data[0])


def load_users() -> Dict[str, User]:
    ensure_default_admin()
    data = user_store.load([])
    return {u["username"]: User(**u) for u in data}


def save_users(users: Dict[str, User]):
    user_store.save([u.dict() for u in users.values()])


def migrate_settings(raw: Dict[str, Any]) -> Tuple[UserSettings, Dict[str, Any]]:
    defaults = UserSettings()
    merged = json.loads(defaults.json())

    def merge(dst, src):
        for key, value in src.items():
            if isinstance(value, dict):
                dst[key] = merge(dst.get(key, {}), value)
            else:
                dst.setdefault(key, value)
        return dst

    migrated = merge(raw or {}, merged)
    return UserSettings(**migrated), migrated


def load_settings() -> Tuple[UserSettings, datetime | None]:
    raw = settings_store.load({})
    settings, migrated = migrate_settings(raw)
    settings_store.save(migrated)
    last_modified = None
    path = settings_store.path
    if path.exists():
        last_modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return settings, last_modified


def save_settings(settings: UserSettings, user: str):
    _, _ = load_settings()
    settings_store.save(json.loads(settings.json()))
    changes = changes_store.load([])
    changes.append(
        ChangeSet(
            id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
            user=user,
            message="Updated settings",
            diff=settings.dict(),
        ).dict()
    )
    changes_store.save(changes)


def list_changes():
    return [ChangeSet(**c) for c in changes_store.load([])]


def save_event(request: BolusRequest, rec: BolusRecommendation):
    events = events_store.load([])
    event = Event(
        id=str(uuid4()),
        timestamp=datetime.now(timezone.utc),
        data=request,
        recommendation=rec,
    )
    events.append(event.dict())
    events_store.save(events)
    return event
