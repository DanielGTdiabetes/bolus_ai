from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.settings import Settings, get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class TokenManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    def create_access_token(self, subject: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=self.settings.security.access_token_minutes)
        to_encode = {"sub": subject, "exp": expire, "iss": self.settings.security.jwt_issuer, "type": "access"}
        return jwt.encode(to_encode, self.settings.security.jwt_secret, algorithm="HS256")

    def create_refresh_token(self, subject: str) -> tuple[str, datetime]:
        expire = datetime.now(timezone.utc) + timedelta(days=self.settings.security.refresh_token_days)
        to_encode = {"sub": subject, "exp": expire, "iss": self.settings.security.jwt_issuer, "type": "refresh"}
        token = jwt.encode(to_encode, self.settings.security.jwt_secret, algorithm="HS256")
        return token, expire

    def decode_token(self, token: str, expected_type: str = "access") -> dict[str, Any]:
        try:
            payload = jwt.decode(token, self.settings.security.jwt_secret, algorithms=["HS256"], issuer=self.settings.security.jwt_issuer)
        except JWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        if payload.get("type") != expected_type:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload

    @staticmethod
    def hash_refresh_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        attempts = [ts for ts in self._attempts.get(key, []) if now - ts <= self.window_seconds]
        attempts.append(now)
        self._attempts[key] = attempts
        return len(attempts) <= self.max_attempts

    def guard(self, key: str):
        if not self.is_allowed(key):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts, try later")


rate_limiter = RateLimiter()


def get_token_manager(settings: Settings = Depends(get_settings)) -> TokenManager:
    return TokenManager(settings)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def auth_required(token: str = Depends(oauth2_scheme), token_manager: TokenManager = Depends(get_token_manager)) -> str:
    payload = token_manager.decode_token(token, expected_type="access")
    return str(payload.get("sub"))


def admin_required(username: str = Depends(auth_required), user_loader: Callable[[str], dict[str, Any]] = None) -> str:
    if user_loader is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User loader not configured")
    user = user_loader(username)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return username
