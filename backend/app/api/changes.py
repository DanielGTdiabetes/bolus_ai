from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.datastore import ChangeStore
from app.core.security import get_current_user
from app.core.settings import Settings, get_settings

router = APIRouter()


def _change_store(settings: Settings = Depends(get_settings)) -> ChangeStore:
    return ChangeStore(Path(settings.data.data_dir) / "changes.json")


@router.get("/", summary="List changes")
async def list_changes(_: dict = Depends(get_current_user), store: ChangeStore = Depends(_change_store)):
    return store.load()



