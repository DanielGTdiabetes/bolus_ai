from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from pathlib import Path

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from app.core.settings import Settings, get_settings

# Make OAuth2 optional so basic endpoints don't crash without token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)



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

    def decode_token(self, token: str, expected_type: str = "access") -> dict[str, Any]:
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No token provided")
        try:
            payload = jwt_decode(token, self.settings.security.jwt_secret, issuer=self.settings.security.jwt_issuer)
        except JWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        if payload.get("type") != expected_type:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload

def get_token_manager(settings: Settings = Depends(get_settings)) -> TokenManager:
    return TokenManager(settings)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        # bcrypt hashes start with $2b$ and include salt and cost factor
        if password_hash.startswith("$2"):
            return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed bcrypt hash
        return False

    # Fallback for legacy SHA-256 hashes to keep backwards compatibility
    legacy_hash = hashlib.sha256(plain_password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_hash, password_hash)


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def auth_required(token: str = Depends(oauth2_scheme), token_manager: TokenManager = Depends(get_token_manager)) -> str:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = token_manager.decode_token(token, expected_type="access")
    return str(payload.get("sub"))


def admin_required(username: str = Depends(auth_required), user_loader: Callable[[str], dict[str, Any]] = None) -> str:
    if user_loader is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User loader not configured")
    user = user_loader(username)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return username



class CurrentUser(BaseModel):
    username: str
    role: str
    needs_password_change: bool = False
    
    @property
    def id(self) -> str:
        return self.username

def get_current_user(
    token: str = Depends(oauth2_scheme),
    token_manager: TokenManager = Depends(get_token_manager),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    from app.core.datastore import UserStore

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = token_manager.decode_token(token, expected_type="access")
    username = str(payload.get("sub"))
    store = UserStore(Path(settings.data.data_dir) / "users.json")
    user_dict = store.find(username)
    if not user_dict:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    
    return CurrentUser(**user_dict)



def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return current_user


def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme), 
    token_manager: TokenManager = Depends(get_token_manager),
    settings: Settings = Depends(get_settings),
) -> Optional[CurrentUser]:
    """
    Returns CurrentUser if token is valid, else None.
    Does NOT raise HTTPException (401).
    Used for webhooks or public endpoints that *can* use auth but don't require it.
    """
    if not token:
        return None
        
    try:
        from app.core.datastore import UserStore
        payload = token_manager.decode_token(token, expected_type="access")
        username = str(payload.get("sub"))
        
        # We need to replicate UserStore loading logic or make it lighter
        # For optional, maybe just returning a dummy user if DB fails?
        # Let's try to load properly
        store = UserStore(Path(settings.data.data_dir) / "users.json")
        user_dict = store.find(username)
        if user_dict:
            return CurrentUser(**user_dict)
    except Exception:
        # If token is invalid or user not found, just return None for optional auth
        pass
        
    return None

