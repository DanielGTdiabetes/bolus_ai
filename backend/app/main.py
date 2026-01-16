import logging
import os
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    data_dir = Path(settings.data.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Using data directory: %s", data_dir)
    
    # Audit H8: Validate Critical Secrets
    if not settings.security.jwt_secret or len(settings.security.jwt_secret) < 16:
         logger.warning("CRITICAL: JWT_SECRET is missing or too short! Encrypted data will be inaccessible or insecure.")
    
    import os
    app_secret = os.environ.get("APP_SECRET_KEY")
    if not app_secret or len(app_secret) < 10:
         logger.warning("CRITICAL: APP_SECRET_KEY (for Nightscout encryption) is missing or too short!")

    # Ensure models are loaded before creating tables
    import app.models 

    from app.core.db import init_db, get_engine, switch_to_cloud_if_needed
    from app.services.auth_repo import init_auth_db
    init_db()
    
    # --- Critical Initialization (Sync) ---
    try:
        logger.info("⏳ Waiting for Database...")
        
        # Emergency Switch Check
        await switch_to_cloud_if_needed()

        await init_auth_db()
        
        # Schema fixes
        from app.core.migration import ensure_basal_schema, ensure_treatment_columns, ensure_ml_schema
        await ensure_basal_schema(get_engine())
        await ensure_treatment_columns(get_engine())
        await ensure_ml_schema(get_engine())

        # Verify critical tables
        from sqlalchemy import text
        try:
             async with get_engine().connect() as conn:
                 await conn.execute(text("SELECT 1 FROM nutrition_drafts LIMIT 1"))
             logger.info("✅ Table 'nutrition_drafts' verification successful.")
        except Exception as e:
             logger.critical(f"❌ Table 'nutrition_drafts' MISSING or inaccessible: {e}")
        
        logger.info("✅ Database ready.")
    except Exception as e:
        logger.critical(f"❌ Critical DB Init Error: {e}", exc_info=True)
        # We re-raise to crash the container if DB is unusable, 
        # but the log above ensures we see WHY before it dies.
        raise e

    # --- Background Jobs (Non-Critical) ---
    import asyncio
    asyncio.create_task(_background_startup_jobs())

    yield
    
    # --- Shutdown ---
    await bot_service.shutdown()


app = FastAPI(title="Bolus AI", version="0.1.0", lifespan=lifespan)

# ... CORS ...

def _collect_cors_origins() -> list[str]:
    # ... (Keep existing implementation)
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

@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok", "service": "bolus-ai"}

@app.get("/api/health/check", include_in_schema=False)
def health_check_direct():
    return {"status": "ok", "direct": True}

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


async def _background_startup_jobs():
    logger.info("🚀 Starting background jobs...")
    try:
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
        # We add a slight delay to allow the server to fully start before bot polling
        await asyncio.sleep(2) 
        await bot_service.initialize()
        
        logger.info("✅ Background initialization complete.")
    except Exception as e:
        logger.error(f"❌ Background initialization FAILED: {e}", exc_info=True)


@app.get("/api/health/bot", include_in_schema=False)
async def bot_health():
    from app.bot.state import health as bot_health_state
    return bot_health_state.to_dict()

# --- Static Files / Frontend Serving ---
static_dir = Path(__file__).parent / "static"

if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        possible_file = static_dir / full_path
        if full_path != "" and possible_file.exists() and possible_file.is_file():
            return FileResponse(possible_file)

        response = FileResponse(static_dir / "index.html")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {"message": "Bolus AI Backend Running (Frontend not built/static dir missing)"}
