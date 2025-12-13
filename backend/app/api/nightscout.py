from fastapi import APIRouter, Depends, Query

from app.models.schemas import NightscoutSGV, NightscoutStatus, Treatment
from app.services.nightscout_client import NightscoutClient
from app.core.security import auth_required

router = APIRouter()


@router.get("/status", response_model=NightscoutStatus, summary="Nightscout status")
async def nightscout_status(
    _: str = Depends(auth_required),
    nightscout_client: NightscoutClient = Depends(NightscoutClient.depends),
) -> NightscoutStatus:
    return await nightscout_client.get_status()


@router.get("/sgv/latest", response_model=NightscoutSGV, summary="Latest glucose value")
async def latest_sgv(
    _: str = Depends(auth_required),
    nightscout_client: NightscoutClient = Depends(NightscoutClient.depends),
) -> NightscoutSGV:
    return await nightscout_client.get_latest_sgv()


@router.get(
    "/treatments/recent",
    response_model=list[Treatment],
    summary="Recent treatments",
)
async def recent_treatments(
    hours: int = Query(24, ge=1, le=168),
    _: str = Depends(auth_required),
    nightscout_client: NightscoutClient = Depends(NightscoutClient.depends),
) -> list[Treatment]:
    return await nightscout_client.get_recent_treatments(hours=hours)
