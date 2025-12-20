from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.db import get_db_session
from app.api.analysis import _data_store
from app.services.store import DataStore
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.services.isf_analysis_service import IsfAnalysisService
from app.models.isf import IsfAnalysisResponse
from app.models.settings import UserSettings

router = APIRouter()

@router.get("/analysis", response_model=IsfAnalysisResponse, summary="Analyze ISF using methods")
async def analyze_isf(
    days: int = Query(14, ge=7, le=90),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    store: DataStore = Depends(_data_store) # Legacy settings store for profiles
):
    user_id = current_user.username
    
    # 1. Get Nightscout Config
    db_ns_config = await get_ns_config(db, user_id)
    final_url = None
    final_token = None
    
    if db_ns_config and db_ns_config.enabled and db_ns_config.url:
        final_url = db_ns_config.url
        final_token = db_ns_config.api_secret
    else:
        # Fallback local settings (just in case)
        from app.services.settings_service import get_user_settings_service
        try:
             # Try DB again for safety if get_ns_config failed or returned empty but maybe settings has something? 
             # Actually get_ns_config already checks DB. 
             # So we check Store as last resort.
             local_settings = store.load_settings()
             ns = local_settings.get("nightscout", {})
             if ns.get("url"):
                  final_url = ns.get("url")
                  final_token = ns.get("token")
        except Exception:
            pass
    
    if not final_url:
        raise HTTPException(status_code=400, detail="Nightscout not configured")
        
    client = NightscoutClient(base_url=final_url, token=final_token)
    
    # 2. Get User Profile Settings (ISF, IOB)
    from app.services.settings_service import get_user_settings_service
    
    try:
        data = await get_user_settings_service(user_id, db)
        user_settings = None
        if data and data.get("settings"):
            user_settings = UserSettings.migrate(data["settings"])
        else:
            raw_settings = store.load_settings()
            user_settings = UserSettings.migrate(raw_settings)

        current_cf = {
            "breakfast": user_settings.cf.breakfast,
            "lunch": user_settings.cf.lunch,
            "dinner": user_settings.cf.dinner
        }
        
        profile_settings = {
            "dia_hours": user_settings.iob.dia_hours,
            "curve": user_settings.iob.curve,
            "peak_minutes": user_settings.iob.peak_minutes
        }
    except Exception as e:
        await client.aclose()
        raise HTTPException(status_code=500, detail=f"Error loading user settings: {e}")
    
    service = IsfAnalysisService(client, current_cf, profile_settings)
    
    try:
        result = await service.run_analysis(user_id, days)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
    finally:
        await client.aclose()
