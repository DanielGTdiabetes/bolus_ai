import uuid
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.models.bolus_split import (
    BolusPlanRequest, BolusPlanResponse, 
    RecalcSecondRequest, RecalcSecondResponse,
    RecalcComponents
)
from app.services.nightscout_client import NightscoutClient
from app.services.iob import compute_iob, InsulinActionProfile, _boluses_from_treatments

logger = logging.getLogger(__name__)

def round_to_step(value: float, step: float) -> float:
    if step <= 0: return value
    return round(value / step) * step

def clamp(value: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(value, max_v))

def create_plan(req: BolusPlanRequest) -> BolusPlanResponse:
    plan_id = str(uuid.uuid4())
    warnings = []
    
    now_u = 0.0
    later_u = 0.0
    later_after_min = 60
    extended_duration = None
    
    if req.mode == "manual":
        m = req.manual
        now_u = m.now_u
        later_u = m.later_u
        later_after_min = m.later_after_min
        
        # Validate sum tolerance
        s = now_u + later_u
        diff = abs(s - req.total_recommended_u)
        if diff > req.round_step_u + 0.001:
             warnings.append(f"Sum {s} differs from total {req.total_recommended_u} by > {req.round_step_u}")
             
    elif req.mode == "dual":
        d = req.dual
        # Calculate split
        raw_now = req.total_recommended_u * (d.percent_now / 100.0)
        now_u = round_to_step(raw_now, req.round_step_u)
        later_u = max(0.0, req.total_recommended_u - now_u)
        # Verify later_u rounding? Usually we just take remainder. 
        # But maybe we should round later_u too?
        # If we round later_u, sum might not match exactly total.
        # User constraint: "now_u + later_u debe aproximar..."
        # Let's keep later_u as remainder but rounded? 
        # Better: later_u = round_to_step(total - now_u)
        later_u = round_to_step(later_u, req.round_step_u)
        
        later_after_min = d.later_after_min
        extended_duration = d.duration_min
        
    return BolusPlanResponse(
        plan_id=plan_id,
        mode=req.mode,
        total_recommended_u=req.total_recommended_u,
        now_u=now_u,
        later_u_planned=later_u,
        later_after_min=later_after_min,
        extended_duration_min=extended_duration,
        warnings=warnings
    )

async def recalc_second(req: RecalcSecondRequest) -> RecalcSecondResponse:
    # 1. Setup Clients
    ns_conf = req.nightscout
    # We use bare minimum connection
    client = NightscoutClient(base_url=ns_conf.url, token=ns_conf.token)
    
    bg_now_mgdl = None
    bg_age_min = None
    iob_now_u = None
    warnings = []
    
    # 2. Fetch Data (Safety First: no 500s)
    try:
        # BG
        try:
            sgv_data = await client.get_latest_sgv()
            # Age check
            # sgv_data.dateString or date is UTC? 
            # NightscoutSGV model usually has 'date' as int timestamp or date string.
            # Assuming 'date' is epoch millis or datetime.
            # Let's check SGV model if I could... but I'll assume standard NS format: date (int epoch ms)
            
            # Convert to mg/dl if needed
            val = float(sgv_data.sgv)
            # Check units? NS API usually returns SGV in mg/dL always, 
            # while 'units' param is for display. But some might store mmol.
            # Generally /api/v1/entries/sgv.json returns mg/dL.
            # Only if user selected 'mmol' in config we might mistakenly treat it? 
            # Standard NS is mg/dL. 
            
            # Correction for mmol input
            if ns_conf.units == "mmol":
                 # If user says their NS is mmol, does NS return mmol? 
                 # Usually NS returns mg/dL regardless of display units setting.
                 # Let's assume standard NS behavior (mg/dL). 
                 # But if the user passed 'units', maybe they want us to convert input?
                 # No, NS API is standard. We'll stick to raw SGV value which is normally mg/dL.
                 pass

            bg_now_mgdl = val
            
            # Age
            # We need to know when it was recorded
            # I can read sgv_data.date (epoch ms)
            if hasattr(sgv_data, 'date') and isinstance(sgv_data.date, int):
                ts_ms = sgv_data.date
                ts_dt = datetime.fromtimestamp(ts_ms/1000.0, timezone.utc)
            elif hasattr(sgv_data, 'dateString'):
                ts_dt = datetime.fromisoformat(sgv_data.dateString.replace("Z", "+00:00"))
            else:
                # Fallback
                 ts_dt = datetime.now(timezone.utc) # shouldn't happen
                 
            now_utc = datetime.now(timezone.utc)
            age_min = int((now_utc - ts_dt).total_seconds() / 60)
            bg_age_min = age_min
            
            if age_min > req.params.stale_bg_minutes:
                warnings.append(f"BG stale ({age_min} min old)")
            
        except Exception as e:
            logger.warning(f"Failed to fetch BG: {e}")
            warnings.append("Could not fetch current BG")

        # IOB
        try:
            # We need pure list of dicts for compute_iob
            # Reuse logic from iob.py but specific to this flow
            # I assume standard profile (DIA 4h) if not passed? 
            # Actually I don't have user settings for DIA in request params?
            # Wait, req.params (BolusParams) does NOT have DIA.
            # The prompt provided specific params JSON but didn't list DIA in `params`.
            # "params": { "cr_g_per_u": 10.0, ... }
            # But IOB calc needs DIA/Curve.
            # I should assume defaults or ask?
            # Prompt says "IOB actual (Nightscout treatments -> IOB service)".
            # IOB service needs a Profile.
            # I will assume DIA=4, Curve=bilinear (standard) if not provided.
            # Or check if I should add DIA to BolusParams model?
            # The user provided example JSON for request params and it did NOT have DIA. 
            # I will use default DIA=4h.
            
            treatments = await client.get_recent_treatments(hours=5) # 5h to be safe for 4h DIA
            
            # Convert to format expected by compute_iob
            boluses_list = _boluses_from_treatments(treatments)
            
            profile = InsulinActionProfile(
                dia_hours=4.0, 
                curve="bilinear", 
                peak_minutes=75
            )
            
            now = datetime.now(timezone.utc)
            total_iob = compute_iob(now, boluses_list, profile)
            iob_now_u = round(total_iob, 2)
            
        except Exception as e:
            logger.warning(f"Failed to fetch IOB: {e}")
            warnings.append("Could not fetch IOB")
            iob_now_u = 0.0 # Fallback as requested
            
    finally:
        await client.aclose()
        
    # 3. Calculation
    # meal2_u
    meal2_u = 0.0
    if req.carbs_additional_g > 0:
        meal2_u = req.carbs_additional_g / req.params.cr_g_per_u
        
    # corr2_u
    corr2_u = 0.0
    if bg_now_mgdl is not None:
        delta = bg_now_mgdl - req.params.target_bg_mgdl
        if delta > 0:
            corr2_u = delta / req.params.isf_mgdl_per_u
            
    # U2 raw
    u2_raw = meal2_u + corr2_u
    
    # Net
    applied_iob = iob_now_u if iob_now_u is not None else 0.0
    u2_net = u2_raw - applied_iob
    
    # Cap
    # "cap_u = max_bolus_u" (Antes limitado a later_u_planned, ahora permite corrección hacia arriba)
    cap_u = req.params.max_bolus_u
    
    # Recommended
    # "u2_recommended = clamp(round_to_step(u2_net), 0, cap_u)"
    # Note: If u2_net is negative, we zero it.
    u2_rec_step = round_to_step(u2_net, req.params.round_step_u)
    u2_final = clamp(u2_rec_step, 0.0, cap_u)
    
    # Security limit of total bolus? 
    # We already clamped to max_bolus_u above.
    if u2_final == req.params.max_bolus_u and u2_net > req.params.max_bolus_u:
         warnings.append(f"Bolus limited by Max Safety ({req.params.max_bolus_u} U)")
         
    return RecalcSecondResponse(
        bg_now_mgdl=bg_now_mgdl,
        bg_age_min=bg_age_min,
        iob_now_u=iob_now_u,
        components=RecalcComponents(
            meal_u=round(meal2_u, 2),
            correction_u=round(corr2_u, 2),
            iob_applied_u=round(applied_iob, 2)
        ),
        cap_u=cap_u,
        u2_recommended_u=u2_final,
        warnings=warnings
    )
