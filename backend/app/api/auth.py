from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.datastore import SessionStore, UserStore
from app.core.security import auth_required, get_token_manager, rate_limiter, verify_password
from app.core.settings import Settings, get_settings

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    username: str
    role: str
    created_at: str
    needs_password_change: bool = False


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserPublic


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordChangeRequest(BaseModel):
    password: str = Field(min_length=8)


def _user_store(settings: Settings = Depends(get_settings)) -> UserStore:
    store = UserStore(Path(settings.data.data_dir) / "users.json")
    store.ensure_seed_admin()
    return store


def _session_store(settings: Settings = Depends(get_settings)) -> SessionStore:
    return SessionStore(Path(settings.data.data_dir) / "sessions.json")


@router.post("/login", response_model=TokenPair, summary="Login")
async def login(
    request: Request,
    payload: LoginRequest,
    settings: Settings = Depends(get_settings),
    users: UserStore = Depends(_user_store),
    sessions: SessionStore = Depends(_session_store),
):
    rate_limiter.guard(request.client.host if request.client else "anonymous")

    user = users.find(payload.username)
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token_manager = get_token_manager(settings)
    access = token_manager.create_access_token(subject=user["username"])
    refresh_token, refresh_exp = token_manager.create_refresh_token(subject=user["username"])
    sessions.add(user["username"], refresh_token, refresh_exp, token_manager)

    return TokenPair(
        access_token=access,
        refresh_token=refresh_token,
        user=UserPublic(
            username=user["username"],
            role=user["role"],
            created_at=user["created_at"],
            needs_password_change=user.get("needs_password_change", False),
        ),
    )


@router.post("/refresh", response_model=RefreshResponse, summary="Refresh access token")
async def refresh_token(
    refresh_token: str = Body(embed=True),
    settings: Settings = Depends(get_settings),
    sessions: SessionStore = Depends(_session_store),
):
    token_manager = get_token_manager(settings)
    payload = token_manager.decode_token(refresh_token, expected_type="refresh")
    username = payload.get("sub")
    if not username or not sessions.is_valid(username, refresh_token, token_manager):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid")
    access = token_manager.create_access_token(subject=username)
    return RefreshResponse(access_token=access)


@router.post("/logout", summary="Logout")
async def logout(
    refresh_token: str = Body(embed=True),
    settings: Settings = Depends(get_settings),
    sessions: SessionStore = Depends(_session_store),
):
    token_manager = get_token_manager(settings)
    sessions.revoke(refresh_token, token_manager)
    return {"ok": True}


@router.get("/me", response_model=UserPublic, summary="Current user")
async def me(username: str = Depends(auth_required), users: UserStore = Depends(_user_store)):
    user = users.find(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserPublic(
        username=user["username"],
        role=user["role"],
        created_at=user["created_at"],
        needs_password_change=user.get("needs_password_change", False),
    )


@router.post("/me/password", summary="Change own password")
async def change_password(
    payload: PasswordChangeRequest,
    username: str = Depends(auth_required),
    users: UserStore = Depends(_user_store),
):
    from app.core.security import hash_password

    updated = users.update(username, {"password_hash": hash_password(payload.password), "needs_password_change": False})
    return {"ok": True, "user": {"username": updated["username"], "role": updated["role"]}}
