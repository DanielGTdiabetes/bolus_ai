from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.core.settings import Settings, get_settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class JWTError(Exception):
    """Minimal JWT error wrapper."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _datetime_encoder(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return int(obj.timestamp())
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def jwt_encode(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64encode(
        json.dumps(payload, default=_datetime_encoder, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = _b64encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header_b64}.{payload_b64}.{signature}"


def jwt_decode(token: str, secret: str, issuer: str | None = None) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature = token.split(".")
    except ValueError as exc:  # pragma: no cover - malformed token
        raise JWTError("Invalid token format") from exc

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_signature = _b64encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    if not hmac.compare_digest(expected_signature, signature):
        raise JWTError("Invalid signature")

    try:
        payload = json.loads(_b64decode(payload_b64))
    except json.JSONDecodeError as exc:  # pragma: no cover - malformed payload
        raise JWTError("Invalid payload") from exc

    if issuer and payload.get("iss") != issuer:
        raise JWTError("Invalid issuer")

    exp = payload.get("exp")
    if exp is not None and time.time() > float(exp):
        raise JWTError("Token expired")

    return payload


class TokenManager:
    def __init__(self, settings: Settings):
        self.settings = settings

    def create_access_token(self, subject: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=self.settings.security.access_token_minutes)
        to_encode = {"sub": subject, "exp": expire, "iss": self.settings.security.jwt_issuer, "type": "access"}
        return jwt_encode(to_encode, self.settings.security.jwt_secret)

    def create_refresh_token(self, subject: str) -> tuple[str, datetime]:
        expire = datetime.now(timezone.utc) + timedelta(days=self.settings.security.refresh_token_days)
        to_encode = {"sub": subject, "exp": expire, "iss": self.settings.security.jwt_issuer, "type": "refresh"}
        token = jwt_encode(to_encode, self.settings.security.jwt_secret)
        return token, expire

    def decode_token(self, token: str, expected_type: str = "access") -> dict[str, Any]:
        try:
            payload = jwt_decode(token, self.settings.security.jwt_secret, issuer=self.settings.security.jwt_issuer)
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
    return hash_password(plain_password) == password_hash


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


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
