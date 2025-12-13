from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, status

from app.core.security import TokenManager, hash_password


class JsonStore:
    def __init__(self, path: Path, default: Any):
        self.path = path
        self.default = default
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Any:
        if not self.path.exists():
            self.save(self.default)
            return self.default
        with self.path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def save(self, data: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)


class UserStore(JsonStore):
    def __init__(self, path: Path):
        super().__init__(path, default=[])

    def ensure_seed_admin(self) -> None:
        users = self.load()
        if not users:
            now = datetime.utcnow().isoformat()
            users.append(
                {
                    "username": "admin",
                    "password_hash": hash_password("admin123"),
                    "role": "admin",
                    "created_at": now,
                    "needs_password_change": True,
                }
            )
            self.save(users)

    def find(self, username: str) -> Optional[dict[str, Any]]:
        for user in self.load():
            if user.get("username") == username:
                return user
        return None

    def update(self, username: str, data: dict[str, Any]) -> dict[str, Any]:
        users = self.load()
        for idx, usr in enumerate(users):
            if usr.get("username") == username:
                users[idx] = {**usr, **data}
                self.save(users)
                return users[idx]
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    def add(self, user: dict[str, Any]) -> dict[str, Any]:
        users = self.load()
        if any(u.get("username") == user.get("username") for u in users):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User exists")
        users.append(user)
        self.save(users)
        return user


class SessionStore(JsonStore):
    def __init__(self, path: Path):
        super().__init__(path, default=[])

    def add(self, username: str, refresh_token: str, expires_at: datetime, token_manager: TokenManager) -> dict[str, Any]:
        session = {
            "username": username,
            "refresh_token_hash": token_manager.hash_refresh_token(refresh_token),
            "expires_at": expires_at.isoformat(),
            "revoked": False,
        }
        sessions = self.load()
        sessions.append(session)
        self.save(sessions)
        return session

    def is_valid(self, username: str, refresh_token: str, token_manager: TokenManager) -> bool:
        token_hash = token_manager.hash_refresh_token(refresh_token)
        now = datetime.utcnow()
        for session in self.load():
            if session.get("username") != username:
                continue
            if session.get("refresh_token_hash") == token_hash and not session.get("revoked"):
                expires = datetime.fromisoformat(session.get("expires_at"))
                return expires > now
        return False

    def revoke(self, refresh_token: str, token_manager: TokenManager) -> None:
        token_hash = token_manager.hash_refresh_token(refresh_token)
        sessions = self.load()
        updated = False
        for session in sessions:
            if session.get("refresh_token_hash") == token_hash:
                session["revoked"] = True
                updated = True
        if updated:
            self.save(sessions)


class ChangeStore(JsonStore):
    def __init__(self, path: Path):
        super().__init__(path, default=[])


class EventStore(JsonStore):
    def __init__(self, path: Path):
        super().__init__(path, default=[])
