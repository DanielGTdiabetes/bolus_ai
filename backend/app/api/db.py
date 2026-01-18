from fastapi import APIRouter, Depends, Header, HTTPException, status, Request
from app.core.db import check_db_health
from app.core.config import get_admin_shared_secret
from app.core.security import get_current_user_optional, CurrentUser

router = APIRouter()

async def require_admin_or_secret(
    request: Request,
    x_admin_secret: str | None = Header(default=None, alias="X-Admin-Secret"),
    user: CurrentUser | None = Depends(get_current_user_optional)
):
    # 1. Check Secret (Fastest & Simplest)
    expected_secret = get_admin_shared_secret()
    if expected_secret and x_admin_secret and x_admin_secret == expected_secret:
        return True

    # 2. Check Admin User
    if user and user.role == "admin":
        return True
        
    # 3. Cloaking: If unauthorized, return 404 Not Found to hide the endpoint
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


@router.get("/health", summary="Check Database Connection")
async def db_health():
    """
    Verifies connectivity to the PostgreSQL database (Neon).
    """
    return await check_db_health()

@router.get("/force-init", summary="Force DB Initialization")
async def force_db_init(
    authorized: bool = Depends(require_admin_or_secret)
):
    from app.core.db import create_tables
    try:
        await create_tables()
        return {"status": "initialized", "message": "Tables created successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
