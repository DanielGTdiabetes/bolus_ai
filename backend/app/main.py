from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError

from .auth import (
    verify_password,
    create_tokens,
    store_refresh_token,
    revoke_refresh,
    validate_refresh,
    decode_token,
    get_current_user,
    require_admin,
    LOGIN_ATTEMPTS,
)
from .config import get_settings
from .models import (
    User,
    UserSettings,
    BolusRequest,
    BolusRecommendation,
    SettingsResponse,
    RefreshRequest,
)
from .storage import (
    load_users,
    load_settings,
    save_settings,
    list_changes,
    save_event,
    ensure_default_admin,
)

app = FastAPI(title="Bolus AI")
settings = get_settings()

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path == "/api/auth/login" and request.method.lower() == "post":
        attempts = LOGIN_ATTEMPTS.setdefault(request.client.host, [])
        now = datetime.now(timezone.utc)
        attempts[:] = [t for t in attempts if (now - t).seconds < 300]
        if len(attempts) >= 5:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")
        attempts.append(now)
    return await call_next(request)


@app.post("/api/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    users = load_users()
    user = users.get(form_data.username)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    access, refresh = create_tokens(user)
    store_refresh_token(user.username, refresh)
    return {"access_token": access, "refresh_token": refresh, "user": user}


@app.post("/api/auth/refresh")
async def refresh(request: RefreshRequest):
    try:
        payload = decode_token(request.refresh_token)
    except HTTPException:
        raise
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if payload.type != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    users = load_users()
    user = users.get(payload.sub)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not validate_refresh(request.refresh_token, user.username):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Revoked token")
    access, refresh_token = create_tokens(user)
    store_refresh_token(user.username, refresh_token)
    return {"access_token": access}


@app.post("/api/auth/logout")
async def logout(user: User = Depends(get_current_user)):
    revoke_refresh(user.username)
    return {"ok": True}


@app.get("/api/auth/me")
async def me(user: User = Depends(get_current_user)):
    return user


@app.get("/api/settings")
async def get_settings_endpoint(user: User = Depends(get_current_user)):
    settings_obj, last_modified = load_settings()
    return SettingsResponse(settings=settings_obj, last_modified=last_modified)


@app.put("/api/settings")
async def update_settings(new_settings: UserSettings, user: User = Depends(require_admin)):
    save_settings(new_settings, user.username)
    return {"ok": True}


@app.get("/api/changes")
async def changes(user: User = Depends(get_current_user)):
    return list_changes()


@app.post("/api/changes/{change_id}/undo")
async def undo_change(change_id: str, user: User = Depends(get_current_user)):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Undo not implemented")


@app.get("/api/glucose/current")
async def glucose_current(user: User = Depends(get_current_user)):
    return {"glucose": 110, "trend": "flat", "timestamp": datetime.now(timezone.utc)}


@app.get("/api/nightscout/status")
async def nightscout_status(user: User = Depends(get_current_user)):
    return {"nightscout_url": settings.nightscout_url, "status": "ok"}


@app.post("/api/bolus/recommend")
async def recommend_bolus(request: BolusRequest, user: User = Depends(get_current_user)):
    settings_obj, _ = load_settings()
    base = request.carbs * settings_obj.cr.breakfast
    rec = BolusRecommendation(
        upfront=round(base * 0.7, 2),
        later=round(base * 0.3, 2),
        delay_min=30 if request.high_fat else 0,
        explanation=[
            "Based on carb ratio and meal timing",
            "Adjusted for fat content" if request.high_fat else "Standard meal",
        ],
    )
    save_event(request, rec)
    return rec


@app.post("/api/events")
async def create_event(request: BolusRequest, user: User = Depends(get_current_user)):
    settings_obj, _ = load_settings()
    base = request.carbs * settings_obj.cr.breakfast
    rec = BolusRecommendation(
        upfront=round(base * 0.7, 2),
        later=round(base * 0.3, 2),
        delay_min=30 if request.high_fat else 0,
        explanation=["Event saved"],
    )
    return save_event(request, rec)


@app.get("/api/events")
async def list_events(user: User = Depends(get_current_user)):
    from .storage import events_store

    return events_store.load([])


@app.on_event("startup")
async def startup_event():
    ensure_default_admin()
    load_settings()
