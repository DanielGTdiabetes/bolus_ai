import logging
import os
from pathlib import Path

from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api import api_router
from app.bot import webhook as bot_webhook
from app.bot import service as bot_service
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

    # Add Render's own URL if present
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        env_origins.append(render_url.strip())

    collected: list[str] = []
    for origin in (*default_origins, *configured_origins, *env_origins):
        if origin and origin not in collected:
            # Ensure no trailing slashes in origins
            collected.append(origin.rstrip("/"))

    return collected


app.add_middleware(
    CORSMiddleware,
    allow_origins=_collect_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok", "service": "bolus-ai"}

@app.get("/api/health/check", include_in_schema=False)
def health_check_direct():
    return {"status": "ok", "direct": True, "emergency_mode": settings.emergency_mode}

app.include_router(api_router, prefix="/api")
app.include_router(bot_webhook.router, prefix="/api/webhook")
app.include_router(bot_webhook.diag_router, prefix="/api/bot/telegram")

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger = logging.getLogger("uvicorn.error")
        logger.error(f"🔥 UNHANDLED EXCEPTION: {e}", exc_info=True)
        return Response(content=f"Internal Server Error: {str(e)}", status_code=500)


@app.on_event("startup")
async def startup_event() -> None:
    data_dir = Path(settings.data.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Using data directory: %s", data_dir)
    
    
    # Audit H8: Validate Secret Key (JWT + App Secret)
    # If key is missing, crypto will fail at runtime. Better to fail early.
    if not settings.security.jwt_secret or len(settings.security.jwt_secret) < 16:
         logger.warning("CRITICAL: JWT_SECRET is missing or too short! Encrypted data will be inaccessible or insecure.")
         # if os.environ.get("ENV") == "production":
         #    raise RuntimeError("JWT_SECRET missing in production")
    
    import os
    app_secret = os.environ.get("APP_SECRET_KEY")
    if not app_secret or len(app_secret) < 10:
         logger.warning("CRITICAL: APP_SECRET_KEY (for Nightscout encryption) is missing or too short!")
         # if os.environ.get("ENV") == "production":
         #   raise RuntimeError("APP_SECRET_KEY missing/weak in production")

    # Ensure models are loaded before creating tables
    
    # Ensure models are loaded before creating tables
    import app.models 

    from app.core.db import init_db, create_tables, get_engine
    from app.services.auth_repo import init_auth_db
    init_db()
    
    # --- Critical Initialization (Sync) ---
    # We await DB init to ensure tables exist before serving requests.
    try:
        logger.info("⏳ Waiting for Database...")
        # AUDIT FIX: Removed auto-creation in favor of Alembic migrations.
        await create_tables() 
        await init_auth_db()
        
        # Schema fixes
        from app.core.migration import ensure_basal_schema, ensure_treatment_columns, ensure_ml_schema
        await ensure_basal_schema(get_engine())
        await ensure_treatment_columns(get_engine())
        await ensure_ml_schema(get_engine())


        # Verify critical tables

        
        logger.info("✅ Database ready.")
    except Exception as e:
        logger.critical(f"❌ Critical DB Init Error: {e}")
        raise e

    # --- Background Jobs (Non-Critical) ---
    import asyncio
    asyncio.create_task(_background_startup_jobs())

async def _background_startup_jobs():
    if settings.emergency_mode:
        logger.warning("⚠️ EMERGENCY MODE ACTIVE: Running in restricted state (Monitor Only).")
        # We allow setup_periodic_tasks to run because it now handles the conditional logic internally.
    else:
        logger.info("🚀 Starting background jobs (Full Mode)...")
        # 0. SAFETY FIRST: Rescue Sync from Nightscout (Recover IOB/COB)
        try:
            from app.services.rescue_sync import run_rescue_sync
            await run_rescue_sync(hours=6)
        except Exception as e:
            logger.error(f"Startup Rescue Sync failed: {e}")

    try:
        # DB is already init
        # DB is already init
        from app.core.datastore import UserStore
        data_dir = Path(settings.data.data_dir)

        try:
            UserStore(data_dir / "users.json").ensure_seed_admin()
            logger.info("Admin user check completed")
        except Exception as e:
            logger.warning(f"Could not init user store: {e}")

        # Setup Background Jobs
        try:
            from app.jobs import setup_periodic_tasks
            setup_periodic_tasks()
        except Exception as e:
            logger.error(f"Failed to setup background jobs: {e}")
            
        # Initialize Telegram Bot (Sidecar)
        await bot_service.initialize()
        
        logger.info("✅ Background initialization complete.")
    except Exception as e:
        logger.error(f"❌ Background initialization FAILED: {e}", exc_info=True)

@app.on_event("shutdown")
async def shutdown_event() -> None:
    # Shutdown Telegram Bot
    try:
        await bot_service.shutdown()
    except Exception as exc:
        logger.warning("Telegram bot shutdown failed: %s", exc)
    
    # placeholder for cleanup hooks
    return None


@app.get("/api/health/bot", include_in_schema=False)
async def bot_health():
    from app.bot.state import health as bot_health_state
    return bot_health_state.to_dict()

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
