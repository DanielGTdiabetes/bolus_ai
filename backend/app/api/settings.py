from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.datastore import ChangeStore, JsonStore, UserStore
from app.core.security import auth_required
from app.core.settings import Settings, get_settings
from app.models.settings import UserSettings

router = APIRouter()


def _settings_store(settings: Settings = Depends(get_settings)) -> JsonStore:
    path = Path(settings.data.data_dir) / "settings.json"
    default = UserSettings.default().dict()
    return JsonStore(path, default)


def _changes_store(settings: Settings = Depends(get_settings)) -> ChangeStore:
    return ChangeStore(Path(settings.data.data_dir) / "changes.json")


def _user_store(settings: Settings = Depends(get_settings)) -> UserStore:
    store = UserStore(Path(settings.data.data_dir) / "users.json")
    store.ensure_seed_admin()
    return store


def _require_admin(username: str = Depends(auth_required), users: UserStore = Depends(_user_store)) -> str:
    user = users.find(username)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return username


@router.get("/", response_model=UserSettings, summary="Get settings")
async def get_settings_endpoint(
    _: str = Depends(auth_required),
    store: JsonStore = Depends(_settings_store),
):
    data = store.load()
    try:
        return UserSettings.migrate(data)
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid settings file")


@router.put("/", response_model=UserSettings, summary="Update settings")
async def update_settings_endpoint(
    payload: UserSettings,
    username: str = Depends(_require_admin),
    store: JsonStore = Depends(_settings_store),
    changes: ChangeStore = Depends(_changes_store),
):
    store.save(payload.dict())
    history = changes.load()
    history.append({"by": username, "timestamp": __import__("datetime").datetime.utcnow().isoformat(), "summary": "Settings updated"})
    changes.save(history)
    return payload
