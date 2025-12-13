from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.security import get_current_user
from app.core.settings import Settings, get_settings
from app.models.settings import UserSettings
from app.services.bolus import BolusRequestData, BolusResponse, recommend_bolus
from app.services.iob import compute_iob_from_sources
from app.services.nightscout_client import NightscoutClient, NightscoutError
from app.services.store import DataStore

router = APIRouter()


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))


def _nightscout_client(settings: Settings = Depends(get_settings)) -> Optional[NightscoutClient]:
    if settings.nightscout.base_url:
        return NightscoutClient(settings=settings)
    return None


class BolusRequest(BaseModel):
    carbs_g: float = Field(ge=0)
    bg_mgdl: Optional[float] = Field(default=None, ge=0)
    meal_slot: Literal["breakfast", "lunch", "dinner"]
    target_mgdl: Optional[float] = Field(default=None, ge=60)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class BolusRecommendation(BaseModel):
    upfront_u: float
    later_u: float
    delay_min: Optional[int]
    iob_u: float
    explain: list[str]


@router.post("/recommend", response_model=BolusRecommendation, summary="Recommend bolus")
async def recommend(
    payload: BolusRequest,
    _: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    store: DataStore = Depends(_data_store),
    nightscout: Optional[NightscoutClient] = Depends(_nightscout_client),
):
    user_settings: UserSettings = store.load_settings()

    explain: list[str] = []
    resolved_bg = payload.bg_mgdl

    if resolved_bg is None:
        if nightscout:
            try:
                sgv = await nightscout.get_latest_sgv()
                resolved_bg = float(sgv.sgv)
                explain.append("BG obtenido desde Nightscout")
            except NightscoutError:
                resolved_bg = user_settings.targets.mid
                explain.append("No se pudo obtener BG; se usó objetivo como referencia")
        else:
            resolved_bg = user_settings.targets.mid
            explain.append("BG no enviado; se usó objetivo por defecto")

    now = datetime.now(timezone.utc)
    iob_u, breakdown = await compute_iob_from_sources(now, user_settings, nightscout, store)

    bolus_request = BolusRequestData(
        carbs_g=payload.carbs_g,
        bg_mgdl=resolved_bg,
        meal_slot=payload.meal_slot,
        target_mgdl=payload.target_mgdl,
    )
    recommendation: BolusResponse = recommend_bolus(bolus_request, user_settings, iob_u)

    iob_explain: list[str] = []
    if breakdown:
        for item in breakdown[:5]:
            iob_explain.append(
                f"Bolo {item['units']}U en {item['ts']} aporta {item['iob']:.2f}U activos"
            )
        if len(breakdown) > 5:
            iob_explain.append(f"... {len(breakdown) - 5} bolos adicionales")
    else:
        iob_explain.append("Sin bolos previos registrados")

    recommendation.explain = explain + recommendation.explain + iob_explain
    return recommendation
