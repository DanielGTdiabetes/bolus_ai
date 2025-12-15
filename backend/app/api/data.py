from fastapi import APIRouter, Depends
from app.core.security import get_current_user, CurrentUser
from app.services.export_service import export_all_user_data

router = APIRouter(prefix="/data", tags=["data"])

@router.get("/export")
async def export_user_history(current_user: CurrentUser = Depends(get_current_user)):
    """
    Download all user data (Basal, Settings, Suggestions) as JSON.
    """
    return await export_all_user_data(current_user.id)
