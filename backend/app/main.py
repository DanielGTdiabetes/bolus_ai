from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.api import api_router
from app.core.logging import configure_logging
from app.core.settings import get_settings

configure_logging()
settings = get_settings()

app = FastAPI(title="Bolus AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.security.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/", summary="Root")
async def root() -> dict[str, str]:
    return {"message": "Bolus AI backend is running"}


@app.on_event("startup")
async def startup_event() -> None:
    Path(settings.data.data_dir).mkdir(parents=True, exist_ok=True)
    from app.core.datastore import UserStore

    UserStore(Path(settings.data.data_dir) / "users.json").ensure_seed_admin()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    # placeholder for cleanup hooks
    return None
