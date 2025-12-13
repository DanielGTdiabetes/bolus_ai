from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.security import get_current_user
from app.core.settings import Settings, get_settings
from app.models.settings import UserSettings
from app.models.schemas import NightscoutSGV

from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2, GlucoseUsed
from app.services.bolus_engine import calculate_bolus_v2

from app.services.iob import compute_iob_from_sources
from app.services.nightscout_client import NightscoutClient, NightscoutError
from app.services.store import DataStore

router = APIRouter()


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))


@router.post("/recommend", response_model=BolusResponseV2, summary="Recommend bolus (V2 Engine)")
async def recommend(
    payload: BolusRequestV2,
    _: dict = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
):
    user_settings: UserSettings = store.load_settings()

    # 1. Resolver Glucosa (Manual vs Nightscout)
    resolved_bg: Optional[float] = payload.bg_mgdl
    
    # Init vars
    bg_source: Literal["manual", "nightscout", "none"] = "manual" if resolved_bg is not None else "none"
    bg_trend: Optional[str] = None
    bg_age_minutes: Optional[float] = None
    bg_is_stale: bool = False
    
    # Init NS Client if needed
    ns_client: Optional[NightscoutClient] = None
    ns_config = user_settings.nightscout
    
    # Priority: Manual > Nightscout (if enabled and manual is None)
    if resolved_bg is None and ns_config.enabled and ns_config.url:
         try:
            ns_client = NightscoutClient(
                base_url=ns_config.url,
                token=ns_config.token,
                timeout_seconds=5
            )
            sgv: NightscoutSGV = await ns_client.get_latest_sgv()
            
            # Extract data
            resolved_bg = float(sgv.sgv)
            bg_source = "nightscout"
            bg_trend = sgv.direction
            
            # Calculate Age
            # sgv.date is epoch ms (int)
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            diff_ms = now_ms - sgv.date
            diff_min = diff_ms / 60000.0
            
            bg_age_minutes = diff_min
            if diff_min > 10: # Stale threshold
                 bg_is_stale = True

         except Exception:
            # Fallback will be handled by engine (bg=None)
            bg_source = "none"
            pass # Engine will handle None BG.

    # 2. Calcular IOB
    # Ensure NS client exists if we need it for IOB (history) even if BG was manual
    if ns_client is None and ns_config.enabled and ns_config.url:
         ns_client = NightscoutClient(
            base_url=ns_config.url,
            token=ns_config.token,
            timeout_seconds=5
         )

    try:
        now = datetime.now(timezone.utc)
        iob_u, breakdown = await compute_iob_from_sources(now, user_settings, ns_client, store)
        
        # 3. Llamar al Motor V2
        glucose_info = GlucoseUsed(
            mgdl=resolved_bg,
            source=bg_source,
            trend=bg_trend,
            age_minutes=bg_age_minutes,
            is_stale=bg_is_stale
        )
        
        response = calculate_bolus_v2(
            request=payload,
            settings=user_settings,
            iob_u=iob_u,
            glucose_info=glucose_info
        )
        
        # Enriquecer explain con detalle IOB
        if breakdown:
             response.explain.append(f"   (IOB basado en {len(breakdown)} eventos recientes)")
        
        return response

    finally:
        if ns_client:
            await ns_client.aclose()
