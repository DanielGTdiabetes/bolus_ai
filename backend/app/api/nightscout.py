from pathlib import Path
from typing import Optional, Literal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import get_current_user
from app.core.settings import get_settings, Settings
from app.models.settings import UserSettings
from app.models.schemas import NightscoutSGV
from app.services.nightscout_client import NightscoutClient, NightscoutError
from app.services.store import DataStore
from app.core.db import get_db_session
from app.services.nightscout_secrets_service import get_ns_config, upsert_ns_config
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import CurrentUser

router = APIRouter()



class NightscoutStatusResponse(BaseModel):
    enabled: bool
    url: Optional[str]
    ok: bool
    error: Optional[str] = None


class StatelessConfig(BaseModel):
    url: str
    token: Optional[str] = None
    units: Optional[str] = "mgdl"


class CurrentGlucoseResponse(BaseModel):
    ok: bool
    configured: bool = False
    bg_mgdl: Optional[float] = None
    trend: Optional[str] = None
    trendArrow: Optional[str] = None
    age_minutes: Optional[float] = None
    date: Optional[int] = None
    stale: bool = False
    source: Literal["nightscout"] = "nightscout"
    error: Optional[str] = None


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))


@router.get("/status", response_model=NightscoutStatusResponse, summary="Get Nightscout status (Server-Stored)")
async def get_status(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    ns = await get_ns_config(session, user.username)
    
    ok = False
    error = None
    url = None
    enabled = False
    
    if ns and ns.enabled and ns.url:
        url = ns.url
        enabled = ns.enabled
        try:
            client = NightscoutClient(base_url=ns.url, token=ns.api_secret, timeout_seconds=5)
            try:
                await client.get_status()
                ok = True
            except Exception as e:
                error = str(e)
            finally:
                await client.aclose()
        except Exception as e:
             error = str(e)
    
    return NightscoutStatusResponse(
        enabled=enabled,
        url=url,
        ok=ok,
        error=error,
    )


@router.post("/current", response_model=CurrentGlucoseResponse, summary="Get current glucose (Stateless)")
async def get_current_glucose_stateless(
    config: StatelessConfig,
    _: dict = Depends(get_current_user),
):
    import logging
    logger = logging.getLogger(__name__)

    if not config.url:
        # Request says: 400 if missing url, but we can also return JSON with configured=False
        # "IMPORTANTE: no devolver 200 con “no configurado”." -> implies 400 or checking configured.
        # But if body has empty url, raising HTTPException(400) is standard.
        raise HTTPException(status_code=400, detail="Missing Nightscout URL")

    logger.debug(f"Fetching Nightscout glucose from: {config.url} (token hidden)")

    try:
        client = NightscoutClient(base_url=config.url, token=config.token, timeout_seconds=10)
        try:
            # We don't check "status" first, just get SGV to be fast
            sgv: NightscoutSGV = await client.get_latest_sgv()
            
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            diff_ms = now_ms - sgv.date
            diff_min = diff_ms / 60000.0

            # Trend arrow mapping
            arrows = {
                "DoubleUp": "↑↑", "SingleUp": "↑", "FortyFiveUp": "↗",
                "Flat": "→", "FortyFiveDown": "↘", "SingleDown": "↓", "DoubleDown": "↓↓"
            }
            arrow = arrows.get(sgv.direction, sgv.direction)

            return CurrentGlucoseResponse(
                ok=True,
                configured=True,
                bg_mgdl=float(sgv.sgv),
                trend=sgv.direction,
                trendArrow=arrow,
                age_minutes=diff_min,
                date=int(sgv.date),
                stale=diff_min > 10,
                source="nightscout"
            )

        except NightscoutError as nse:
            logger.error(f"Nightscout client error: {nse}")
            # Request says 502 if Nightscout fails
            raise HTTPException(status_code=502, detail=f"Nightscout Error: {str(nse)}")
        except Exception as e:
            logger.exception("Unexpected error fetching glucose")
            raise HTTPException(status_code=502, detail=f"Unexpected Error: {str(e)}")
        finally:
            await client.aclose()

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Global error in current glucose")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current", response_model=CurrentGlucoseResponse, summary="Get current glucose (Server-Stored)")
async def get_current_glucose_server(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    ns = await get_ns_config(session, user.username)
    if not ns or not ns.enabled or not ns.url:
         raise HTTPException(status_code=400, detail="Nightscout is not configured")
    
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        client = NightscoutClient(base_url=ns.url, token=ns.api_secret, timeout_seconds=10)
        try:
            sgv: NightscoutSGV = await client.get_latest_sgv()
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            diff_ms = now_ms - sgv.date
            diff_min = diff_ms / 60000.0

            arrows = {
                "DoubleUp": "↑↑", "SingleUp": "↑", "FortyFiveUp": "↗",
                "Flat": "→", "FortyFiveDown": "↘", "SingleDown": "↓", "DoubleDown": "↓↓"
            }
            arrow = arrows.get(sgv.direction, sgv.direction)

            return CurrentGlucoseResponse(
                ok=True,
                configured=True,
                bg_mgdl=float(sgv.sgv),
                trend=sgv.direction,
                trendArrow=arrow,
                age_minutes=diff_min,
                date=int(sgv.date),
                stale=diff_min > 10,
                source="nightscout"
            )
        finally:
            await client.aclose()
    except NightscoutError as nse:
        raise HTTPException(status_code=502, detail=str(nse))
    except Exception as e:
        logger.exception("Error fetching current glucose (server)")
        raise HTTPException(status_code=500, detail=str(e))


class TestResponse(BaseModel):
    ok: bool
    reachable: bool
    message: str
    nightscoutVersion: Optional[str] = None


@router.post("/test", response_model=TestResponse, summary="Test Nightscout connection (Stateless)")
async def test_connection_stateless(
    config: StatelessConfig,
    _: dict = Depends(get_current_user),
):
    if not config.url:
        return TestResponse(ok=False, reachable=False, message="URL is required")

    try:
        client = NightscoutClient(base_url=config.url, token=config.token, timeout_seconds=10)
        try:
            status = await client.get_status()
            # Try to get version from status? NightscoutStatus model might have it or not.
            # Assuming status has 'version' field if defined in schema, otherwise explicit check? 
            # NightscoutStatus schema in backend/app/models/schemas.py isn't visible here but lets assume.
            return TestResponse(
                ok=True, 
                reachable=True, 
                message="Conexión exitosa a Nightscout",
                nightscoutVersion=getattr(status, "version", "Unknown")
            )
        except Exception as e:
            return TestResponse(ok=False, reachable=False, message=f"Error conectando: {str(e)}")
        finally:
            await client.aclose()
    except Exception as e:
        return TestResponse(ok=False, reachable=False, message=f"System error: {str(e)}")


class LegacyConfigPayload(BaseModel):
    url: str
    token: str
    enabled: bool = True

@router.put("/config", summary="Update Nightscout configuration (Legacy Backwards Compatibility)")
async def update_config_legacy(
    payload: LegacyConfigPayload,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    # Map 'token' to 'api_secret'
    await upsert_ns_config(session, user.username, payload.url, payload.token, payload.enabled)
    return {"message": "Config updated via legacy endpoint"}


@router.get("/treatments", summary="Get recent treatments (Server-Stored)")
async def get_treatments_server(
    count: int = 20,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Fetches recent treatments using the server-stored Nightscout configuration (Secrets DB).
    """
    ns = await get_ns_config(session, user.username)
    
    if not ns or not ns.enabled or not ns.url:
         raise HTTPException(status_code=400, detail="Nightscout is not configured or enabled on the server.")

    try:
        # Note: ns.api_secret is the decrypted secret from DB
        client = NightscoutClient(base_url=ns.url, token=ns.api_secret, timeout_seconds=10)
        try:
            # We fetch roughly last 48h to be safe, limited by count
            treatments = await client.get_recent_treatments(hours=48, limit=count)
            return treatments
        finally:
            await client.aclose()
            
    except NightscoutError as nse:
        # Pass through the Nightscout error as 502
         raise HTTPException(status_code=502, detail=str(nse))
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Error fetching treatments")
        raise HTTPException(status_code=500, detail=str(e)) 


