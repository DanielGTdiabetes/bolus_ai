from fastapi import APIRouter
from app.core.db import check_db_health

router = APIRouter()

@router.get("/health", summary="Check Database Connection")
async def db_health():
    """
    Verifies connectivity to the PostgreSQL database (Neon).
    """
    return await check_db_health()

@router.get("/force-init", summary="Force DB Initialization")
async def force_db_init():
    from app.core.db import create_tables
    try:
        await create_tables()
        return {"status": "initialized", "message": "Tables created successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
