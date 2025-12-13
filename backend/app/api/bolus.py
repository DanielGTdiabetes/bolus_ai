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


@router.post("/calc", response_model=BolusResponseV2, summary="Calculate bolus (Stateless V2)")
async def calculate_bolus_stateless(
    payload: BolusRequestV2,
    _: dict = Depends(get_current_user),
    store: DataStore = Depends(_data_store),
):
    # 1. Resolve Settings
    # If payload has settings, construct a temporary UserSettings object to satisfy the engine interface
    # Otherwise load from store (Legacy mode)
    
    if payload.settings:
        # Construct UserSettings adaptor from payload
        # This allows reusing existing engine logic without rewriting it all
        from app.models.settings import InsulinSettings, CarbRatioSettings, SensitivitySettings, TargetSettings, IOBSettings, NightscoutSettings
        
        # We map meal slots to the structure UserSettings expects
        cr_settings = CarbRatioSettings(
            breakfast=payload.settings.breakfast.icr,
            lunch=payload.settings.lunch.icr,
            dinner=payload.settings.dinner.icr
        )
        isf_settings = SensitivitySettings(
            breakfast=payload.settings.breakfast.isf,
            lunch=payload.settings.lunch.isf,
            dinner=payload.settings.dinner.isf
        )
        # For targets, UserSettings uses low/mid/high range. We only have single target per slot in stateless.
        # We can set 'mid' to the target of the requested slot, or just mock it.
        # The engine uses: target = request.target_mgdl or settings.targets.mid
        # We will ensure request.target_mgdl is populated from the slot if not provided.
        target_settings = TargetSettings(
            low=70, 
            mid=100, # Placeholder
            high=180
        )
        
        iob_settings = IOBSettings(
             dia_hours=payload.settings.dia_hours,
             curve="bilinear", # Default
             peak_minutes=75 
        )
        
        # NS from payload
        ns_settings = NightscoutSettings(
            enabled=bool(payload.nightscout and payload.nightscout.url),
            url=payload.nightscout.url if payload.nightscout else "",
            token=payload.nightscout.token if payload.nightscout else ""
        )
        
        user_settings = UserSettings(
            cr=cr_settings,
            cf=isf_settings,
            targets=target_settings,
            iob=iob_settings,
            nightscout=ns_settings,
            max_bolus_u=payload.settings.max_bolus_u,
            max_correction_u=payload.settings.max_correction_u,
            round_step_u=payload.settings.round_step_u
        )
        
        # Pre-fill target from slot if not in request
        if payload.target_mgdl is None:
             slot_profile = getattr(payload.settings, payload.meal_slot)
             payload.target_mgdl = slot_profile.target

    else:
        # Legacy: Load from DB
        user_settings = store.load_settings()


    # 2. Resolve Nightscout Client
    ns_client: Optional[NightscoutClient] = None
    ns_config = user_settings.nightscout
    
    # If payload has explicit NS config, use it (override)
    if payload.nightscout:
        ns_config.enabled = True
        ns_config.url = payload.nightscout.url
        ns_config.token = payload.nightscout.token

    # 3. Resolve Glucose (Manual vs Nightscout)
    resolved_bg: Optional[float] = payload.bg_mgdl
    bg_source: Literal["manual", "nightscout", "none"] = "manual" if resolved_bg is not None else "none"
    bg_trend: Optional[str] = None
    bg_age_minutes: Optional[float] = None
    bg_is_stale: bool = False
    
    # Priority: Manual > Nightscout 
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
            
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            diff_ms = now_ms - sgv.date
            diff_min = diff_ms / 60000.0
            
            bg_age_minutes = diff_min
            if diff_min > 10: 
                 bg_is_stale = True

         except Exception:
            bg_source = "none"
            pass 

    # 4. Calculate IOB
    # Ensure client exists if needed for IOB even if BG was manual
    if ns_client is None and ns_config.enabled and ns_config.url:
         ns_client = NightscoutClient(
            base_url=ns_config.url,
            token=ns_config.token,
            timeout_seconds=5
         )

    try:
        now = datetime.now(timezone.utc)
        iob_u, breakdown = await compute_iob_from_sources(now, user_settings, ns_client, store)
        
        # 5. Call Engine
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
        
        if breakdown:
             response.explain.append(f"   (IOB basado en {len(breakdown)} tratamientos recientes)")
        
        return response

    finally:
        if ns_client:
            await ns_client.aclose()
