from fastapi import APIRouter

from .health import router as health_router
from .nightscout import router as nightscout_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(nightscout_router, prefix="/nightscout", tags=["nightscout"])

__all__ = ["api_router"]
