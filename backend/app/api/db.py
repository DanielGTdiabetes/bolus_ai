from fastapi import APIRouter
from app.core.db import check_db_health

router = APIRouter()

@router.get("/health", summary="Check Database Connection")
async def db_health():
    """
    Verifies connectivity to the PostgreSQL database (Neon).
    """
    return await check_db_health()
