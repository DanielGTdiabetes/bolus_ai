import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.logging import configure_logging
from app.core.settings import get_settings

configure_logging()
settings = get_settings()
logger = logging.getLogger(__name__)

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
    data_dir = Path(settings.data.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Using data directory: %s", data_dir)

    from app.core.datastore import UserStore

    admin_created = UserStore(data_dir / "users.json").ensure_seed_admin()
    if admin_created:
        logger.info("Default admin user created (username='admin')")
    else:
        logger.info("Default admin user already present")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    # placeholder for cleanup hooks
    return None
