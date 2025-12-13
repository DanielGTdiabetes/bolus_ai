from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.datastore import ChangeStore
from app.core.security import auth_required
from app.core.settings import Settings, get_settings

router = APIRouter()


def _change_store(settings: Settings = Depends(get_settings)) -> ChangeStore:
    return ChangeStore(Path(settings.data.data_dir) / "changes.json")


@router.get("/", summary="List changes")
async def list_changes(_: str = Depends(auth_required), store: ChangeStore = Depends(_change_store)):
    return store.load()


@router.post("/{change_id}/undo", summary="Undo change (stub)")
async def undo_change(change_id: int, _: str = Depends(auth_required)):
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Undo not implemented yet")
