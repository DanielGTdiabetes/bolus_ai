from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.security import get_current_user
from app.core.settings import Settings, get_settings
from app.models.settings import UserSettings
from app.models.schemas import NightscoutSGV
from app.services.bolus import BolusRequestData, BolusResponse, recommend_bolus
from app.services.iob import compute_iob_from_sources
from app.services.nightscout_client import NightscoutClient, NightscoutError
from app.services.store import DataStore

router = APIRouter()


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))


class BolusRequest(BaseModel):
    carbs_g: float = Field(ge=0)
    bg_mgdl: Optional[float] = Field(default=None, ge=0)
    meal_slot: Literal["breakfast", "lunch", "dinner"]
    target_mgdl: Optional[float] = Field(default=None, ge=60)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class GlucoseInfo(BaseModel):
    mgdl: Optional[float]
    source: Literal["manual", "nightscout", "none"]
    trend: Optional[str] = None


class BolusRecommendation(BaseModel):
    upfront_u: float
    later_u: float
    delay_min: Optional[int]
    iob_u: float
    explain: list[str]
    # Transparency
    cr_used: float
    cf_used: float
    glucose: GlucoseInfo


@router.post("/recommend", response_model=BolusRecommendation, summary="Recommend bolus")
async def recommend(
    payload: BolusRequest,
    _: dict = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
):
    user_settings: UserSettings = store.load_settings()

    explain: list[str] = []
    
    # 1. Resolve Glucose
    resolved_bg: Optional[float] = payload.bg_mgdl
    bg_source: Literal["manual", "nightscout", "none"] = "manual" if resolved_bg is not None else "none"
    bg_trend: Optional[str] = None

    ns_client: Optional[NightscoutClient] = None
    ns_config = user_settings.nightscout
    
    # Only try Nightscout if manual BG is missing
    if resolved_bg is None and ns_config.enabled and ns_config.url:
         try:
            ns_client = NightscoutClient(
                base_url=ns_config.url,
                token=ns_config.token,
                timeout_seconds=5
            )
            sgv: NightscoutSGV = await ns_client.get_latest_sgv()
            resolved_bg = float(sgv.sgv)
            bg_source = "nightscout"
            bg_trend = sgv.direction
            explain.append(f"BG usado: {resolved_bg} mg/dL (Nightscout {sgv.direction or ''})")
         except Exception as exc:
            # Fallback
            explain.append(f"Fallo Nightscout: {str(exc)}. Se ignora corrección.")
            resolved_bg = None
            bg_source = "none"
    elif resolved_bg is None:
         explain.append("BG vacío y Nightscout deshabilitado/no configurado.")

    # 2. IOB Calculation
    # Note: access IOB using same NS client or new one? 
    # compute_iob_from_sources creates simple client if passed None but needs URL/token.
    # We can pass our ns_client if it exists and is open. 
    # But compute_iob handles client lifecycle internally if None passed?
    # Actually compute_iob_from_sources takes `nightscout_client` argument.
    
    # Re-init client if closed or not created? 
    # If we created ns_client above, we reuse it.
    # If not created (manual BG), we might still want IOB from Nightscout!
    
    if ns_client is None and ns_config.enabled and ns_config.url:
         ns_client = NightscoutClient(
            base_url=ns_config.url,
            token=ns_config.token,
            timeout_seconds=5
         )

    try:
        now = datetime.now(timezone.utc)
        iob_u, breakdown = await compute_iob_from_sources(now, user_settings, ns_client, store)
        
        # 3. Calculate Bolus
        bolus_request = BolusRequestData(
            carbs_g=payload.carbs_g,
            bg_mgdl=resolved_bg,
            meal_slot=payload.meal_slot,
            target_mgdl=payload.target_mgdl,
        )
        
        result: BolusResponse = recommend_bolus(bolus_request, user_settings, iob_u)
        
        # Merge explains
        final_explain = explain + result.explain
        
        # Add basic IOB info to explain
        if breakdown:
            total_events = len(breakdown)
            final_explain.append(f"IOB basado en {total_events} eventos recientes.")
        else:
            final_explain.append("IOB: 0 (Sin historial reciente)")

        return BolusRecommendation(
            upfront_u=result.upfront_u,
            later_u=result.later_u,
            delay_min=result.delay_min,
            iob_u=result.iob_u,
            explain=final_explain,
            cr_used=result.cr_used,
            cf_used=result.cf_used,
            glucose=GlucoseInfo(
                mgdl=resolved_bg,
                source=bg_source,
                trend=bg_trend
            )
        )

    finally:
        if ns_client:
            await ns_client.aclose()
