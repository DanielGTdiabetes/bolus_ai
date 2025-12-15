import logging
import os
from pathlib import Path

from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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


@app.on_event("startup")
async def startup_event() -> None:
    data_dir = Path(settings.data.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Using data directory: %s", data_dir)
    
    # Ensure models are loaded before creating tables
    import app.models 

    from app.core.db import init_db, create_tables, get_engine
    init_db()
    await create_tables()
    
    # Hotfix: Ensure schema for Basal Checkin
    from app.core.migration import ensure_basal_schema
    await ensure_basal_schema(get_engine())

    from app.core.datastore import UserStore

    try:
        UserStore(data_dir / "users.json").ensure_seed_admin()
        logger.info("Admin user check completed")
    except Exception as e:
        logger.warning(f"Could not init user store: {e}")

@app.on_event("shutdown")
async def shutdown_event() -> None:
    # placeholder for cleanup hooks
    return None

# --- Static Files / Frontend Serving ---
# Serve the built frontend from app/static (populated during build)
static_dir = Path(__file__).parent / "static"

if static_dir.exists():
    # 1. Serve assets with long cache (Vite handles hashing)
    #    Mount at /assets
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    # 2. Catch-all to serve index.html for SPA (and favicon, etc if present)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Use simple logic: if file exists and is not index.html, serve it.
        # Otherwise serve index.html (SPA routing).
        
        # Note: /api routes are handled earlier by app.include_router
        
        possible_file = static_dir / full_path
        if full_path != "" and possible_file.exists() and possible_file.is_file():
            return FileResponse(possible_file)

        # Fallback to index.html
        response = FileResponse(static_dir / "index.html")
        # Prevent caching of index.html to ensure updates are seen immediately
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
else:
    # Fallback for when running backend only (dev mode without build)
    @app.get("/", include_in_schema=False)
    def root():
        return {"message": "Bolus AI Backend Running (Frontend not built/static dir missing)"}

