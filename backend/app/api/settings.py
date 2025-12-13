from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.datastore import ChangeStore, UserStore
from app.core.security import auth_required
from app.core.settings import Settings, get_settings
from app.models.settings import UserSettings
from app.services.store import DataStore

router = APIRouter()


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))


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
    store: DataStore = Depends(_data_store),
):
    data = store.load_settings()
    try:
        return data
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid settings file")


@router.put("/", response_model=UserSettings, summary="Update settings")
async def update_settings_endpoint(
    payload: UserSettings,
    username: str = Depends(_require_admin),
    store: DataStore = Depends(_data_store),
    changes: ChangeStore = Depends(_changes_store),
):
    store.save_settings(payload)
    history = changes.load()
    history.append({"by": username, "timestamp": __import__("datetime").datetime.utcnow().isoformat(), "summary": "Settings updated"})
    changes.save(history)
    return payload
