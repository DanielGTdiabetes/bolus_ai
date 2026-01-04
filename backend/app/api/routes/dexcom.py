from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.security import auth_required
from app.services.dexcom_client import DexcomClient
from app.core.settings import get_settings
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db_session

router = APIRouter()

class TestDexcomRequest(BaseModel):
    username: str
    password: str
    region: str = "ous"

class TestDexcomResponse(BaseModel):
    success: bool
    message: str
    sgv: Optional[int] = None
    timestamp: Optional[str] = None

@router.post("/test", response_model=TestDexcomResponse)
async def test_dexcom_connection(
    payload: TestDexcomRequest, 
    user_id: str = Depends(auth_required),
    db: Optional[AsyncSession] = Depends(get_db_session)
):
    """
    Test connectivity to Dexcom Share with provided credentials.
    """
    try:
        password_to_use = payload.password
        
        # If password is empty, try to fetch from saved settings in DB
        if not password_to_use and db:
             from app.services import settings_service
             user_res = await settings_service.get_user_settings_service(user_id, db)
             settings = user_res.get("settings")
             if settings and "dexcom" in settings:
                 saved_pass = settings["dexcom"].get("password")
                 if saved_pass:
                     password_to_use = saved_pass
        
        if not password_to_use:
             return TestDexcomResponse(
                success=False,
                message="Error: Contraseña no proporcionada y no encontrada en configuración guardada."
            )

        client = DexcomClient(
            username=payload.username, 
            password=password_to_use, 
            region=payload.region
        )
        reading = await client.get_latest_sgv()
        
        if reading:
            return TestDexcomResponse(
                success=True, 
                message=f"Conectado. Valor actual: {reading.sgv} {reading.trend}",
                sgv=reading.sgv,
                timestamp=str(reading.date)
            )
        else:
             return TestDexcomResponse(
                success=True, 
                message="Conectado, pero NO hay datos recientes (Sensor parado?)",
                sgv=None
            )
            
    except Exception as e:
        return TestDexcomResponse(
            success=False,
            message=f"Error de conexión: {str(e)}"
        )
