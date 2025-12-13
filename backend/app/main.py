from fastapi import FastAPI

from app.api import api_router
from app.core.logging import configure_logging
from app.core.settings import get_settings

configure_logging()
settings = get_settings()

app = FastAPI(title="Bolus AI", version="0.1.0")
app.include_router(api_router, prefix="/api")


@app.get("/", summary="Root")
async def root() -> dict[str, str]:
    return {"message": "Bolus AI backend is running"}


@app.on_event("startup")
async def startup_event() -> None:
    _ = settings  # ensure settings loaded early


@app.on_event("shutdown")
async def shutdown_event() -> None:
    # placeholder for cleanup hooks
    return None
