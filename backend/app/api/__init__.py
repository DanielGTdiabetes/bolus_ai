from fastapi import APIRouter

from .auth import router as auth_router
from .bolus import router as bolus_router
from .changes import router as changes_router
from .health import router as health_router
from .nightscout import router as nightscout_router
from .settings import router as settings_router
from .vision import router as vision_router
from .basal import router as basal_router
from .db import router as db_router
from .analysis import router as analysis_router
from .suggestions import router as suggestions_router
from .notifications import router as notifications_router
from .data import router as data_router
from .nightscout_secrets import router as nightscout_secrets_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(nightscout_router, prefix="/nightscout", tags=["nightscout"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(settings_router, prefix="/settings", tags=["settings"])
api_router.include_router(changes_router, prefix="/changes", tags=["changes"])
api_router.include_router(bolus_router, prefix="/bolus", tags=["bolus"])
api_router.include_router(vision_router, prefix="/vision", tags=["vision"])
api_router.include_router(basal_router, prefix="/basal", tags=["basal"])
api_router.include_router(db_router, prefix="/db", tags=["db"])
api_router.include_router(analysis_router, prefix="/analysis", tags=["analysis"])
api_router.include_router(suggestions_router)
api_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
api_router.include_router(data_router)
api_router.include_router(vision_router, prefix="/photo", tags=["vision"], include_in_schema=False)
api_router.include_router(nightscout_secrets_router, prefix="/nightscout", tags=["nightscout_secrets"])

__all__ = ["api_router"]
