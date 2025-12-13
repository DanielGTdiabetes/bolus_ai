from datetime import datetime, timedelta, timezone
from typing import Dict
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from .config import get_settings
from .models import User, TokenPayload, Role
from .storage import load_users, save_users, session_store, pwd_context


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


LOGIN_ATTEMPTS: Dict[str, list[datetime]] = {}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_tokens(user: User):
    settings = get_settings()
    now = datetime.now(timezone.utc)
    access_payload = {
        "sub": user.username,
        "exp": now + timedelta(minutes=15),
        "iss": settings.jwt_issuer,
        "type": "access",
        "role": user.role.value,
    }
    refresh_payload = {
        "sub": user.username,
        "exp": now + timedelta(days=7),
        "iss": settings.jwt_issuer,
        "type": "refresh",
    }
    access_token = jwt.encode(access_payload, settings.jwt_secret, algorithm="HS256")
    refresh_token = jwt.encode(refresh_payload, settings.jwt_secret, algorithm="HS256")
    return access_token, refresh_token


def store_refresh_token(username: str, token: str):
    tokens = session_store.load([])
    tokens = [t for t in tokens if t.get("username") != username or t.get("exp", 0) > datetime.now(timezone.utc).timestamp()]
    tokens.append({
        "username": username,
        "token": get_password_hash(token),
        "exp": datetime.now(timezone.utc).timestamp() + 7 * 24 * 3600,
    })
    session_store.save(tokens)


def revoke_refresh(username: str, token: str | None = None):
    tokens = session_store.load([])
    if token:
        tokens = [t for t in tokens if not (t.get("username") == username and pwd_context.verify(token, t.get("token")))]
    else:
        tokens = [t for t in tokens if t.get("username") != username]
    session_store.save(tokens)


def validate_refresh(token: str, username: str) -> bool:
    tokens = session_store.load([])
    now = datetime.now(timezone.utc).timestamp()
    for t in tokens:
        if t.get("username") == username and now < t.get("exp", 0):
            if pwd_context.verify(token, t.get("token")):
                return True
    return False


def decode_token(token: str) -> TokenPayload:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer=settings.jwt_issuer)
        return TokenPayload(**payload)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    payload = decode_token(token)
    if payload.type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    users = load_users()
    user = users.get(payload.sub)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user
