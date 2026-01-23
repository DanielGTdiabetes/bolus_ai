from fastapi import APIRouter
from app.bot.proactive import get_proactive_status

router = APIRouter()

@router.get("/status")
async def get_bot_proactive_status():
    """
    Returns the last evaluation results for proactive bot modules.
    Useful for diagnostics.
    """
    return get_proactive_status()
