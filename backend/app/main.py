import logging
import os
from pathlib import Path

from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.logging import configure_logging
from app.core.settings import get_settings

configure_logging()
settings = get_settings()
logger = logging.getLogger(__name__)

app = FastAPI(title="Bolus AI", version="0.1.0")


def _collect_cors_origins() -> list[str]:
    default_origins = [
        "https://bolus-ai.onrender.com",
        "https://bolus-ai-1.onrender.com",
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    configured_origins = settings.security.cors_origins
    env_origins = [
        origin.strip()
        for origin in os.environ.get("FRONTEND_ORIGIN", "").split(",")
        if origin.strip()
    ]

    collected: list[str] = []
    for origin in (*default_origins, *configured_origins, *env_origins):
        if origin and origin not in collected:
            collected.append(origin)

    return collected


app.add_middleware(
    CORSMiddleware,
    allow_origins=_collect_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.api_route("/", methods=["GET", "HEAD"], summary="Root", response_model=None)
async def root(request: Request) -> dict[str, str] | Response:
    if request.method == "HEAD":
        return Response(status_code=200)
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
