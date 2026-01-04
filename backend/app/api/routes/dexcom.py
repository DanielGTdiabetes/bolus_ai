from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.security import auth_required
from app.services.dexcom_client import DexcomClient
from app.core.settings import get_settings

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
async def test_dexcom_connection(payload: TestDexcomRequest, user_id: str = Depends(auth_required)):
    """
    Test connectivity to Dexcom Share with provided credentials.
    """
    try:
        client = DexcomClient(payload.username, payload.password, payload.region)
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
