from pathlib import Path
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.datastore import UserStore
from app.core.security import auth_required, get_token_manager, hash_password, verify_password
from app.core.settings import Settings, get_settings

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    username: str
    role: str
    needs_password_change: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


def _user_store(settings: Settings = Depends(get_settings)) -> UserStore:
    store = UserStore(Path(settings.data.data_dir) / "users.json")
    store.ensure_seed_admin()
    return store


def _public_user(user: dict[str, str | bool]) -> UserPublic:
    return UserPublic(
        username=user["username"],
        role=user["role"],
        needs_password_change=user.get("needs_password_change", False),
    )


@router.post("/login", response_model=LoginResponse, summary="Login")
async def login(
    payload: LoginRequest,
    settings: Settings = Depends(get_settings),
    users: UserStore = Depends(_user_store),
):
    user = users.find(payload.username)
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token_manager = get_token_manager(settings)
    access = token_manager.create_access_token(subject=user["username"])

    return LoginResponse(access_token=access, user=_public_user(user))


@router.get("/me", response_model=UserPublic, summary="Current user")
async def me(username: str = Depends(auth_required), users: UserStore = Depends(_user_store)):
    user = users.find(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _public_user(user)


@router.post("/change-password", summary="Change own password")
async def change_password(
    payload: PasswordChangeRequest,
    username: str = Depends(auth_required),
    users: UserStore = Depends(_user_store),
):
    user = users.find(username)
    if not user or not verify_password(payload.old_password, user.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid current password")

    updated = users.update(
        username,
        {"password_hash": hash_password(payload.new_password), "needs_password_change": False},
    )
    return {"ok": True, "user": _public_user(updated)}
