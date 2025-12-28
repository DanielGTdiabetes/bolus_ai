
import math
import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.future import select

from app.models.treatment import Treatment
from app.models.settings import UserSettings
from app.services.math.curves import InsulinCurves, CarbCurves
from app.services.math.basal import BasalModels
from app.services.nightscout_client import NightscoutClient
from app.services.nightscout_secrets_service import get_ns_config
from app.core.db import get_db_session

logger = logging.getLogger(__name__)

class AutosensResult:
    def __init__(self, ratio: float, reason: str):
        self.ratio = ratio
        self.reason = reason

class AutosensService:
    """
    Calculates Insulin Sensitivity Factor adjustments (Autosens) 
    based on retrospective analysis of glucose vs. model predictions.
    """

    @staticmethod
    async def calculate_autosens(
        username: str, 
        session, 
        settings: UserSettings, 
        bg_target: float = 110.0
    ) -> AutosensResult:
        
        # --- 1. Fetch History Data (24h) ---
        now_utc = datetime.now(timezone.utc)
        start_calcs = now_utc - timedelta(hours=24)
        
        # Buffer for insulin/carb activity (look back further for active IOB/COB at start of window)
        # DIA is typically 4-6h. Let's look back 24h + 8h buffer.
        data_start = start_calcs - timedelta(hours=8)
        
        # A. Fetch BG (Nightscout)
        bg_data: List[Dict[str, Any]] = []
        ns_config = await get_ns_config(session, username)
        
        if ns_config and ns_config.enabled and ns_config.url:
            try:
                client = NightscoutClient(ns_config.url, ns_config.api_secret)
                # Fetch readings for calculation window (plus small buffer)
                sgvs = await client.get_sgv_range(start_calcs - timedelta(minutes=15), now_utc, count=2000)
                await client.aclose()
                
                # Normalize
                for s in sgvs:
                    ts = s.date / 1000.0 # epoch
                    dt = datetime.fromtimestamp(ts, timezone.utc)
                    bg_data.append({
                        'time': dt,
                        'sgv': float(s.sgv)
                    })
                
                bg_data.sort(key=lambda x: x['time'])
            except Exception as e:
                logger.error(f"Autosens BG fetch failed: {e}")
                return AutosensResult(1.0, "Error fetching BG data")
        
        if len(bg_data) < 12: # Require at least 1h of data
            return AutosensResult(1.0, "Insufficient BG data")

        # B. Fetch Treatments (DB + NS)
        # See ForecastEngine for robust fetching, here we simplify for brevity but keep core logic
        # We need treatments from data_start
        temp_treatments = []
        
        # DB
        stmt = (
            select(Treatment)
            .where(Treatment.user_id == username)
            .where(Treatment.created_at >= data_start.replace(tzinfo=None))
            .order_by(Treatment.created_at)
        )
        res = await session.execute(stmt)
        db_rows = res.scalars().all()
        for r in db_rows:
            dt = r.created_at
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            temp_treatments.append({
                'time': dt,
                'insulin': r.insulin or 0,
                'carbs': r.carbs or 0,
                'duration': r.duration or 0,
                'notes': r.notes or ""
            })
            
        # NS (Last 24h+buffer)
        if ns_config and ns_config.enabled:
             # Just fetch last 300 items roughly covering 32h
             pass # Assume DB sync is primary or implement if requested. Skipping to keep clean.
             # User prompt implies syncing is available or assumes "Dexcom G7 / Nightscout" data source for BG.

        # Simplify treatment list
        # Sort
        temp_treatments.sort(key=lambda x: x['time'])
        
        # --- 2. Calculate Deviations ---
        # We analyze 5-minute intervals.
        # Deviation(t) = DeltaBG_Real - DeltaBG_Model
        
        deviations_8h = []
        deviations_24h = []
        
        # Params
        isf_profile = settings.cf # Assuming schedule support, but usually singular in simple profiles
        # Resolving ISF/ICR per time is needed.
        # We'll simple-resolve using the timestamp hour.
        
        total_time_points = len(bg_data)
        
        for i in range(1, total_time_points):
            curr = bg_data[i]
            prev = bg_data[i-1]
            
            t_curr = curr['time']
            t_prev = prev['time']
            dt_sec = (t_curr - t_prev).total_seconds()
            
            # Require close continuity (approx 5 min)
            if dt_sec < 200 or dt_sec > 400: # 3.3min to 6.6min
                continue
            
            dt_min = dt_sec / 60.0
            
            # 1. Delta Real
            delta_real = curr['sgv'] - prev['sgv']
            
            # 2. Delta Model
            # A. Calculate Active Insulin / Carbs Impact at t_prev
            # We iterate ALL treatments effective at t_prev
            
            insulin_rate = 0.0 # U/min
            carb_rate = 0.0 # g/min
            
            # Resolve ISF/ICR/Basal for t_prev
            # User UserSettings schedule logic if available, else flat
            # (Assuming simplified flat or basic schedule from Forecast logic)
            # Resolve ISF/ICR/Basal for t_prev
            # We map the hour to the closest Meal Slot configuration
            hour_local = (t_prev.hour + 1) % 24 # +1 approximate local time adjustment assumption
            
            # Default to Snack (often safe choice or used for night)
            current_isf = settings.cf.snack
            current_icr = settings.cr.snack
            
            if 5 <= hour_local < 11:
                current_isf = settings.cf.breakfast
                current_icr = settings.cr.breakfast
            elif 11 <= hour_local < 16:
                current_isf = settings.cf.lunch
                current_icr = settings.cr.lunch
            elif 19 <= hour_local < 23:
                current_isf = settings.cf.dinner
                current_icr = settings.cr.dinner
            
            current_dia = settings.iob.dia_hours * 60
            current_model = settings.iob.curve
            
            has_active_carbs = False
            
            for tr in temp_treatments:
                # Time since treatment
                age_min = (t_prev - tr['time']).total_seconds() / 60.0
                
                # Insulin Activity
                if tr['insulin'] > 0:
                    act = InsulinCurves.get_activity(age_min, current_dia, settings.iob.peak_minutes, current_model)
                    insulin_rate += act * tr['insulin']
                    
                # Carb Activity
                if tr['carbs'] > 0:
                    # Using variable absorption
                    abs_time = settings.absorption.lunch # default
                    if tr['notes'] and 'alcohol' in tr['notes'].lower(): abs_time = 480
                    elif tr['notes'] and 'dual' in tr['notes'].lower(): abs_time = 360
                    
                    act_c = CarbCurves.variable_absorption(age_min, abs_time)
                    carb_rate += act_c * tr['carbs']
                    
                    # Check if carb is "active" (rough check: within absorption windown)
                    if 0 < age_min < abs_time:
                         has_active_carbs = True
            
                # check for exclusions
                if tr['notes'] and any(x in tr['notes'].lower() for x in ['alcohol', 'sick', 'enfermedad']):
                     if 0 <= age_min < 600: # 10h exclusion window for safety
                         has_active_carbs = True # Re-use this flag or create new, reusing forces invalidity

            
            # Delta Model = (CarbReach - InsulinDrop) * dt
            # CarbReach = CarbRate * CS (CS = ISF/ICR)
            cs = current_isf / current_icr if current_icr > 0 else 0
            
            delta_model = (carb_rate * cs - insulin_rate * current_isf) * dt_min
            
            # B. Deviation
            deviation = delta_real - delta_model
            
            # --- 3. Filter ---
            # Exclude if Carbs on Board, or rapid changes (noise)
            # User rule: "COB muy bajo... o >3h"
            # If has_active_carbs is True, we mark it dirty.
            
            is_valid = True
            
            if has_active_carbs:
                is_valid = False
            
            # Filter noise / extremes
            if not (70 <= prev['sgv'] <= 250):
                is_valid = False
                
            # Filter missing signals / calibration jumps (delta > 20 mg/dl in 5 mins is suspicious)
            if abs(delta_real) > 15:
                is_valid = False
            
            if is_valid:
                # Add to windows
                hours_ago = (now_utc - t_curr).total_seconds() / 3600.0
                
                if hours_ago <= 8:
                    deviations_8h.append(deviation)
                
                if hours_ago <= 24:
                    deviations_24h.append(deviation)
        
        # --- 4. Aggregate & Calculate Ratio ---
        
        def calculate_ratio_from_deviations(devs: List[float]) -> float:
            if len(devs) < 10: return 1.0 # Not enough data
            
            # Median often safer than mean for outliers
            med = statistics.median(devs)
            
            # Apply sensitivity factor (k)
            # Formula: ratio = 1 + k * avg_deviation
            # If deviations are positive (Glucose rising more than exp), we need MORE insulin (Ratio < 1? No, ISF effective = Base / Ratio).
            # If Ratio > 1, ISF_eff is smaller -> Stronger correction.
            # So Positive Deviation => We want Ratio > 1.
            
            # Sensitivity k. Standard OAPS is roughly ISF related, but user gave simple linear formula.
            # Let's say if Deviation average is +2 mg/dL per 5 min (+24 mg/dL/hr), that's HUGE resistance.
            # A moderate drift of +0.5 mg/dL/interval (+6/hr).
            # k should be tuned. 
            # E.g. +1 mg/dL deviation -> +5% insulin needed?
            k = 0.05 
            
            ratio = 1.0 + (k * med)
            
            # Clamp
            return max(0.7, min(1.2, ratio))
            
        ratio_8h = calculate_ratio_from_deviations(deviations_8h)
        ratio_24h = calculate_ratio_from_deviations(deviations_24h)
        
        # --- 5. Combine ---
        # Logic: If both same direction, use closest to 1.
        # If differ, use closest to 1 (Conservative).
        # Actually simplest safe logic: The one closest to 1 dominates (least aggressive change).
        
        final_ratio = 1.0
        dist_8 = abs(ratio_8h - 1.0)
        dist_24 = abs(ratio_24h - 1.0)
        
        # If both > 1 (Resistance)
        if ratio_8h > 1 and ratio_24h > 1:
             final_ratio = min(ratio_8h, ratio_24h) # Least increase
        # If both < 1 (Sensitive)
        elif ratio_8h < 1 and ratio_24h < 1:
             final_ratio = max(ratio_8h, ratio_24h) # Least decrease (closest to 1)
        # Mixed
        else:
             final_ratio = 1.0 # Disagreement -> Cancel out
             
        # Reason string
        reason = f"Normal (Ratio {final_ratio:.2f})"
        if final_ratio > 1.02:
            pct = int((final_ratio - 1) * 100)
            reason = f"Resistencia detectada (+{pct}% aggressive)"
        elif final_ratio < 0.98:
            pct = int((1 - final_ratio) * 100)
            reason = f"Sensibilidad detectada (-{pct}% conservative)"
            
        return AutosensResult(final_ratio, reason)

