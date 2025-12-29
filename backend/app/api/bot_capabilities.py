from fastapi import APIRouter

from app.bot.capabilities.registry import build_registry
from app import jobs_state


router = APIRouter(prefix="/bot", tags=["bot"])


@router.get("/capabilities", summary="Lista el registro de capacidades del bot")
async def list_capabilities() -> dict:
    registry = build_registry()
    return registry.to_safe_dict()


@router.get("/jobs/status", summary="Estado agregado de jobs de bot/scheduler")
async def bot_jobs_status() -> dict:
    registry = build_registry()
    jobs = registry.to_safe_dict().get("jobs", [])
    states = jobs_state.get_all_states()
    return {"jobs": jobs, "states": states}
