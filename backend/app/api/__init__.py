from fastapi import APIRouter

from .auth import router as auth_router
from .bolus import router as bolus_router
from .changes import router as changes_router
from .health import router as health_router
from .nightscout import router as nightscout_router
from .settings import router as settings_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(nightscout_router, prefix="/nightscout", tags=["nightscout"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(settings_router, prefix="/settings", tags=["settings"])
api_router.include_router(changes_router, prefix="/changes", tags=["changes"])
api_router.include_router(bolus_router, prefix="/bolus", tags=["bolus"])

__all__ = ["api_router"]
