import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from app.core.security import get_current_user
from app.core.settings import get_settings, Settings
from app.core.config import get_vision_provider, get_google_api_key, get_gemini_model
from app.models.settings import UserSettings
from app.models.vision import (
    VisionEstimateRequest,
    VisionEstimateResponse,
    GlucoseUsed,
    VisionBolusRecommendation,
)
from app.services.bolus import BolusRequestData, BolusResponse, recommend_bolus
from app.services.iob import compute_iob_from_sources
from app.services.nightscout_client import NightscoutClient
from app.services.store import DataStore
from app.services.vision import estimate_meal_from_image, calculate_extended_split

router = APIRouter()
logger = logging.getLogger(__name__)

# Rate limiting: user_id -> list of timestamps
_rate_limits: dict[str, list[float]] = {}


class VisionStatus(BaseModel):
    provider: str
    configured: bool
    has_api_key: bool
    model: str


def _check_rate_limit(username: str):
    now = time.time()
    timestamps = _rate_limits.get(username, [])
    # Filter out older than 10 min (600s)
    waiting_window = 600
    valid = [t for t in timestamps if now - t < waiting_window]
    
    if len(valid) >= 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded (10 images / 10 min)"
        )
    
    valid.append(now)
    _rate_limits[username] = valid


def _data_store(settings: Settings = Depends(get_settings)) -> DataStore:
    return DataStore(Path(settings.data.data_dir))


@router.get("/status", response_model=VisionStatus, summary="Get vision provider status")
def get_vision_status():
    provider = get_vision_provider()
    has_key = False
    model = ""
    
    if provider == "gemini":
        has_key = bool(get_google_api_key())
        model = get_gemini_model()
    elif provider == "openai":
        settings = get_settings()
        has_key = bool(settings.vision.openai_api_key)
        model = "gpt-4o"
    
    return VisionStatus(
        provider=provider,
        configured=(provider != "none" and has_key),
        has_api_key=has_key,
        model=model
    )


@router.post("/estimate", response_model=VisionEstimateResponse, summary="Estimate carbs from image")
async def estimate_from_image(
    image: UploadFile = File(...),
    # Optional fields form-encoded
    meal_slot: Optional[str] = Form("lunch"),
    bg_mgdl: Optional[int] = Form(None),
    target_mgdl: Optional[int] = Form(None),
    portion_hint: Optional[str] = Form(None),
    prefer_extended: bool = Form(True),
    
    nightscout_url: Optional[str] = Form(None),
    nightscout_token: Optional[str] = Form(None),
    
    current_user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    store: DataStore = Depends(_data_store),
):
    start_ts = time.time()
    username = current_user["username"]
    _check_rate_limit(username)

    provider = get_vision_provider()
    
    # 1. Validation using new config helpers
    if provider == "gemini":
        if not get_google_api_key():
             logger.warning(f"Vision request failed: missing Google API Key (provider={provider})")
             raise HTTPException(status_code=501, detail="missing_google_api_key: Gemini API Key not configured")
    elif provider == "openai":
         if not settings.vision.openai_api_key:
             logger.warning(f"Vision request failed: missing OpenAI API Key (provider={provider})")
             raise HTTPException(status_code=501, detail="OpenAI API Key not configured")
    else:
         logger.warning(f"Vision request failed: unknown/disabled provider ({provider})")
         raise HTTPException(status_code=501, detail=f"Vision provider not configured (current: {provider})")

    # Image Size Check
    max_bytes = settings.vision.max_image_mb * 1024 * 1024
    if image.size and image.size > max_bytes:
        raise HTTPException(status_code=413, detail=f"Image too large (> {settings.vision.max_image_mb}MB)")
    
    if image.content_type not in ["image/jpeg", "image/png", "image/webp"]:
         raise HTTPException(status_code=415, detail="Unsupported image type")

    # Read bytes
    content = await image.read()
    size_mb = len(content) / (1024 * 1024)
    if len(content) > max_bytes:
         raise HTTPException(status_code=413, detail=f"Image too large (> {settings.vision.max_image_mb}MB)")

    logger.info(f"Vision Analysis Start: provider={provider}, user={username}, size={size_mb:.2f}MB, slot={meal_slot}")

    # 2. Vision Estimation
    hints = {
        "meal_slot": meal_slot,
        "portion_hint": portion_hint,
    }
    
    # Update settings with our resolved env vars to ensure service uses them
    # (Since service logic often reads from settings object)
    if provider == "gemini":
        # Hack/Patch: inject the key so generic calling code works
        settings.vision.provider = "gemini" 
        settings.vision.google_api_key = get_google_api_key()
    
    try:
        estimate = await estimate_meal_from_image(content, image.content_type, hints, settings)
        duration = (time.time() - start_ts) * 1000
        logger.info(f"Vision Analysis Success: user={username}, carbs={estimate.carbs_estimate_g}g, time={duration:.0f}ms")
    except RuntimeError as e:
        logger.error(f"Vision Analysis Error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error in vision analysis")
        raise HTTPException(status_code=500, detail="Internal server error during analysis")

    # 3. Bolus Calculation Context
    user_settings: UserSettings = store.load_settings()
    
    # 3a. Resolve BG
    resolved_bg = bg_mgdl
    ns_source = None
    
    if resolved_bg is None:
        ns_config = user_settings.nightscout
        
        # Effective NS config: Request Params > Stored Config
        eff_ns_url = nightscout_url if nightscout_url else (ns_config.url if ns_config.enabled else None)
        eff_ns_token = nightscout_token if nightscout_token else ns_config.token
        
        if eff_ns_url:
            logger.info(f"Vision trying to fetch BG from NS: {eff_ns_url}")
            try:
                ns_client_iob = NightscoutClient(
                    base_url=eff_ns_url,
                    token=eff_ns_token,
                    timeout_seconds=5
                )
                sgv = await ns_client_iob.get_latest_sgv()
                resolved_bg = float(sgv.sgv)
                ns_source = "nightscout"
                logger.info(f"Vision NS Success: {resolved_bg} mg/dL")
            except Exception as e:
                logger.error(f"Vision NS Fetch Failed: {e}")
                pass
            finally:
                if 'ns_client_iob' in locals():
                    await ns_client_iob.aclose()

    estimate.glucose_used = GlucoseUsed(
        mgdl=resolved_bg, 
        source=ns_source if ns_source else ("manual" if bg_mgdl else None)
    )

    # 3b. Compute IOB
    ns_client_iob = None
    ns_config = user_settings.nightscout
    
    eff_ns_url = nightscout_url if nightscout_url else (ns_config.url if ns_config.enabled else None)
    eff_ns_token = nightscout_token if nightscout_token else ns_config.token

    if eff_ns_url:
         ns_client_iob = NightscoutClient(
                base_url=eff_ns_url,
                token=eff_ns_token,
                timeout_seconds=5
        )
    
    try:
        # Note: compute_iob_from_sources also checks Settings if ns_client_iob is not provided
        # But here we provide a constructed client, effectively overriding
        now = datetime.now(timezone.utc)
        # We pass our explicit client
        iob_u, breakdown = await compute_iob_from_sources(now, user_settings, ns_client_iob, store)
    finally:
         if ns_client_iob:
             await ns_client_iob.aclose()
    
    # 3c. Calculate Bolus
    effective_bg = resolved_bg if resolved_bg is not None else user_settings.targets.mid
    
    bolus_req = BolusRequestData(
        carbs_g=estimate.carbs_estimate_g,
        bg_mgdl=effective_bg,
        meal_slot=meal_slot if meal_slot in ["breakfast", "lunch", "dinner"] else "lunch",
        target_mgdl=target_mgdl
    )
    
    bolus_res: BolusResponse = recommend_bolus(bolus_req, user_settings, iob_u)
    
    # 4. Extended logic
    final_upfront = bolus_res.upfront_u
    final_later = 0.0
    delay_min = None
    kind = "normal"
    explain = bolus_res.explain[:]
    
    # Heuristic for extended
    should_extend = prefer_extended and (estimate.fat_score >= 0.6 or estimate.slow_absorption_score >= 0.6)
    
    # If standard bolus recommends a correction only (carbs=0?), we shouldn't extend correction usually.
    # But estimate comes from carbs. If carbs > 0.
    
    if should_extend and estimate.carbs_estimate_g > 0 and final_upfront > 0:
        # We start from the 'later' recommendation of the standard calc? 
        # Actually recommend_bolus returns 'upfront_u' as the total recommended immediate bolus.
        # But wait, recommend_bolus logic might already split? 
        # Looking at bolus.py: recommend_bolus returns upfront_u and later_u=0 usually unless configured otherwise.
        # The prompt says: "Reutiliza services/bolus.py para calcular el TOTAL... Luego, si kind='extended': split del total"
        
        total_u = bolus_res.upfront_u + bolus_res.later_u # Assuming standard calc might return later_u=0
        
        # Calculate split
        items_names = [i.name for i in estimate.items]
        raw_upfront, raw_later, delay = calculate_extended_split(
            total_u, 
            estimate.fat_score, 
            estimate.slow_absorption_score,
            items_names
        )
        
        # Rounding (step 0.05)
        step = user_settings.round_step_u
        def round_step(val):
            return round(val / step) * step

        final_upfront = round_step(raw_upfront)
        final_later = round_step(total_u - final_upfront)
        
        # Safety checks
        if effective_bg < 70 or total_u <= 0:
             # Hypo risk: do not extend, give all upfront (or usually 0 if hypo)
             kind = "normal"
             final_upfront = total_u
             final_later = 0
             delay_min = None
             explain.append("Riesgo hipoglucemia o bolo nulo: cancelado bolo extendido.")
        else:
             kind = "extended"
             delay_min = delay
             explain.append(f"Detectado alto contenido graso/lento (Fat: {estimate.fat_score:.1f}). Estrategia extendida.")
             explain.append("IMPORTANTE: 'later_u' es una recomendación para pinchar más tarde (MDI).")
    else:
         # Normal
         final_later = bolus_res.later_u # usually 0
         delay_min = bolus_res.delay_min
    
    # 5. Missing BG warning
    if resolved_bg is None:
        estimate.bolus = None
        # We force user input for BG? Prompt says: 
        # "Si no hay Nightscout y bg_mgdl es null: devuelve bolus=null y needs_user_input pidiendo BG"
        explain.append("Falta valor de glucosa para cálculo preciso.")
        from app.models.vision import UserInputQuestion
        estimate.needs_user_input.append(UserInputQuestion(
            id="bg_input",
            question="No se ha detectado glucosa. Introduce tu glucosa actual.",
            options=[]
        ))
    else:
        estimate.bolus = VisionBolusRecommendation(
            upfront_u=final_upfront,
            later_u=final_later,
            delay_min=delay_min,
            iob_u=iob_u,
            explain=explain,
            kind=kind
        )

    return estimate
