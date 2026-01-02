from pathlib import Path
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, status, Request
import time
from collections import defaultdict
from pydantic import BaseModel, Field

from app.core.datastore import UserStore
from app.core.security import auth_required, get_token_manager, hash_password, verify_password
from app.core.settings import Settings, get_settings

router = APIRouter()

# Rate Limiting State (In-Memory)
# Key: IP_Username, Value: list of timestamps
_login_attempts = defaultdict(list)
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60


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


@router.post("/login", response_model=LoginResponse, summary="Login")
async def login(
    payload: LoginRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    # Audit: Rate Limiting
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}_{payload.username}"
    now = time.time()
    
    # Filter old attempts
    _login_attempts[rate_key] = [t for t in _login_attempts[rate_key] if now - t < WINDOW_SECONDS]
    
    if len(_login_attempts[rate_key]) >= MAX_ATTEMPTS:
         logger.warning(f"Rate limit exceeded for {rate_key}")
         raise HTTPException(status_code=429, detail="Demasiados intentos de inicio de sesión. Espere 1 minuto.")

    from app.services.auth_repo import get_user_by_username
    user = await get_user_by_username(payload.username)
    
    if not user:
        _login_attempts[rate_key].append(now)
        # Check legacy/fallback if DB migration isn't full?
        # Or just fail.
        # Fallback to local store for initial migration if needed, but 'init_auth_db' should have seeded admin.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(payload.password, user.get("password_hash", "")):
        _login_attempts[rate_key].append(now)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token_manager = get_token_manager(settings)
    access = token_manager.create_access_token(subject=user["username"])

    return LoginResponse(access_token=access, user=_public_user(user))


@router.get("/me", response_model=UserPublic, summary="Current user")
async def me(username: str = Depends(auth_required)):
    from app.services.auth_repo import get_user_by_username
    user = await get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _public_user(user)


@router.post("/change-password", summary="Change own password")
async def change_password(
    payload: PasswordChangeRequest,
    username: str = Depends(auth_required),
):
    from app.services.auth_repo import get_user_by_username, update_user
    user = await get_user_by_username(username)
    
    if not user or not verify_password(payload.old_password, user.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid current password")

    updated = await update_user(
        username,
        {"password_hash": hash_password(payload.new_password), "needs_password_change": False},
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update password")
        
    return {"ok": True, "user": _public_user(updated)}

class ProfileChangeRequest(BaseModel):
    new_username: str = Field(min_length=3)
    password: str # Required to confirm identity before such a big change

@router.post("/change-profile", summary="Update profile (username)")
async def change_profile(
    payload: ProfileChangeRequest,
    settings: Settings = Depends(get_settings),
    username: str = Depends(auth_required),
):
    from app.services.auth_repo import get_user_by_username, rename_user
    
    # 1. Verify password
    user = await get_user_by_username(username)
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Contraseña incorrecta")

    new_username = payload.new_username.strip()
    if new_username == username:
         return {"ok": True, "user": _public_user(user), "token": None}

    # 2. Rename
    success = await rename_user(username, new_username)
    if not success:
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe o error en base de datos")

    # 3. Issue new token
    # Since username changed, old token subject is invalid for next request
    token_manager = get_token_manager(settings)
    new_token = token_manager.create_access_token(subject=new_username)
    
    # Return new user obj
    updated_user = await get_user_by_username(new_username)

    return {
        "ok": True, 
        "user": _public_user(updated_user),
        "access_token": new_token
    }

def _public_user(user: dict) -> UserPublic:
    return UserPublic(
        username=user["username"],
        role=user.get("role", "user"),
        needs_password_change=user.get("needs_password_change", False),
    )
