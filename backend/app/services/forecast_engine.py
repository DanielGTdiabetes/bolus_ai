import math
import logging
from typing import List, Tuple, Dict, Optional
from datetime import datetime, timezone

from app.models.forecast import (
    ForecastSimulateRequest, ForecastResponse, 
    ForecastPoint, ComponentImpact, ForecastSummary
)
from app.services.math.curves import InsulinCurves, CarbCurves
from app.services.math.basal import BasalModels

logger = logging.getLogger(__name__)

class ForecastEngine:
    
    @staticmethod
    def calculate_forecast(req: ForecastSimulateRequest) -> ForecastResponse:
        
        # 1. Initialize State
        current_bg = req.start_bg
        delta_t = req.step_minutes
        horizon = req.horizon_minutes
        
        # Simulation Arrays
        time_points = list(range(0, horizon + 1, delta_t))
        series: List[ForecastPoint] = []
        components: List[ComponentImpact] = []
        warnings: List[str] = []
        quality = "high"

        # 2. Momentum (Retrospective Analysis)
        # Calculate initial slope (mg/dL per minute)
        momentum_slope = 0.0
        if req.momentum and req.momentum.enabled and req.recent_bg_series:
            momentum_slope, m_warnings = ForecastEngine._calculate_momentum(
                req.recent_bg_series, 
                req.momentum.lookback_points
            )
            warnings.extend(m_warnings)
            # Downgrade quality if momentum failed
            if m_warnings:
                quality = "medium"
        
        # Decay momentum over time (linear 30 mins or exponential?)
        # Loop standard is usually ~30 mins decay.
        # We will decay it linearly to 0 over 30 mins to avoid long-term drift errors.
        momentum_duration = 30 
        
        # 3. Main Simulation Loop - Hybrid Deviation Approach
        
        # A. Calculate Model "Zero-Time" Slope (What physics says should be happening NOW)
        # We need this to correct the Momentum. 
        # If Model says "Drop -2" and Reality is "Drop -2", deviation is 0. 
        # Old logic added them to get "-4", causing double counting.
        
        model_slope_0 = 0.0
        
        # Insulin Slope at t=0
        ins_rate_0 = 0.0
        for b in req.events.boluses:
             t_since = 0 - b.time_offset_min
             
             if b.duration_minutes and b.duration_minutes > 10:
                 chunk_step = 5.0
                 n_chunks = math.ceil(b.duration_minutes / chunk_step)
                 u_per_chunk = b.units / n_chunks
                 for k in range(n_chunks):
                     t_chunk_offset = k * chunk_step
                     t_since_chunk = t_since - t_chunk_offset
                     r = InsulinCurves.get_activity(t_since_chunk, req.params.dia_minutes, req.params.insulin_peak_minutes, req.params.insulin_model)
                     ins_rate_0 += r * u_per_chunk
             else:
                 r = InsulinCurves.get_activity(t_since, req.params.dia_minutes, req.params.insulin_peak_minutes, req.params.insulin_model)
                 ins_rate_0 += r * b.units
        
        # Carb Slope at t=0
        carb_rate_0 = 0.0
        for c in req.events.carbs:
             t_since = 0 - c.time_offset_min
             dur = c.absorption_minutes or req.params.carb_absorption_minutes
             r = CarbCurves.variable_absorption(t_since, dur, peak_min=dur/2)
             # Resolve CS
             this_icr = c.icr if c.icr and c.icr > 0 else req.params.icr
             this_cs = (req.params.isf / this_icr) if this_icr > 0 else 0.0
             carb_rate_0 += r * c.grams * this_cs
             
        # Net Model Slope (mg/dL per min)
        # Insulin drops (negative), Carbs rise (positive)
        # ins_rate_0 is U/min. Mult by ISF -> mg/dL/min.
        isf = req.params.isf
        model_slope_0 = carb_rate_0 - (ins_rate_0 * isf)
        
        # B. Calculate Deviation Slope (The "Unknown Force")
        # Deviation = Observed - Model
        # If Observed=-5, Model=-1 (just starting), Deviation = -4 (Resistance/Error or Momentum)
        deviation_slope = 0.0
        if req.momentum and req.momentum.enabled and momentum_slope != 0:
            deviation_slope = momentum_slope - model_slope_0
            
            # Dampening: If deviation is huge (>3), cap it to avoid panic loops
            if abs(deviation_slope) > 3.0:
                 warnings.append(f"Desviación masiva detectada ({deviation_slope:.1f}), amortiguada.")
                 deviation_slope = 3.0 if deviation_slope > 0 else -3.0
                 quality = "medium"

        # Increase momentum influence duration for smoother blending (~45 mins)
        momentum_duration = 45 

        # C. Simulation Loop
        
        current_sim_bg = current_bg
        
        # Initial State
        series.append(ForecastPoint(t_min=0, bg=current_sim_bg))
        components.append(ComponentImpact(
            t_min=0, 
            momentum_impact=round(deviation_slope, 2) # Just for debug visibility
        ))
        
        accum_insulin_impact = 0.0
        accum_carb_impact = 0.0
        accum_basal_impact = 0.0
        
        for i in range(1, len(time_points)):
            t = time_points[i]
            prev_t = time_points[i-1]
            dt = t - prev_t
            t_mid = (t + prev_t) / 2.0
            
            # --- 1. Physics Model (Standard) ---
            
            # Insulin
            total_insulin_activity = 0.0
            for b in req.events.boluses:
                t_since_inj = t_mid - b.time_offset_min
                
                # Check for Extended Bolus (Square Wave)
                if b.duration_minutes and b.duration_minutes > 10:
                    # SIMULATE SQUARE WAVE
                    # We treat it as N small boluses spread over duration.
                    # This is computationally expensive but accurate.
                    # Optimization: Analytical convolution if possible, but discrete summation is safer for now.
                    
                    # Split into 5-minute chunks
                    chunk_step = 5.0
                    n_chunks = math.ceil(b.duration_minutes / chunk_step)
                    u_per_chunk = b.units / n_chunks
                    
                    # Iterate chunks
                    for k in range(n_chunks):
                        # Center of the chunk
                        t_chunk_offset = k * chunk_step
                        t_since_chunk = t_since_inj - t_chunk_offset
                        
                        rate = InsulinCurves.get_activity(t_since_chunk, req.params.dia_minutes, req.params.insulin_peak_minutes, req.params.insulin_model)
                        total_insulin_activity += rate * u_per_chunk
                else:
                    # Instant Bolus
                    rate = InsulinCurves.get_activity(t_since_inj, req.params.dia_minutes, req.params.insulin_peak_minutes, req.params.insulin_model)
                    total_insulin_activity += rate * b.units
            
            step_insulin_drop = total_insulin_activity * isf * dt
            accum_insulin_impact -= step_insulin_drop
            
            # Carbs
            step_carb_impact_rate = 0.0
            for c in req.events.carbs:
                t_since_meal = t_mid - c.time_offset_min
                dur = c.absorption_minutes or req.params.carb_absorption_minutes
                rate = CarbCurves.variable_absorption(t_since_meal, dur, peak_min=dur/2)
                this_icr = c.icr if c.icr and c.icr > 0 else req.params.icr
                this_cs = (req.params.isf / this_icr) if this_icr > 0 else 0.0
                step_carb_impact_rate += rate * c.grams * this_cs
                
            step_carb_rise = step_carb_impact_rate * dt
            accum_carb_impact += step_carb_rise
            
            # Basal Drift (Checking for injections)
            accum_basal_val = 0.0
            if req.events.basal_injections:
                rate_at_0 = 0.0
                for b in req.events.basal_injections:
                    t_since = 0 - b.time_offset_min
                    rate_at_0 += BasalModels.get_activity(t_since, b.duration_minutes or 1440, b.type, b.units)
                
                rate_at_t = 0.0
                for b in req.events.basal_injections:
                    t_since = t_mid - b.time_offset_min
                    rate_at_t += BasalModels.get_activity(t_since, b.duration_minutes or 1440, b.type, b.units)
                
                basal_drift_rate = (rate_at_0 - rate_at_t) * isf
                accum_basal_impact += basal_drift_rate * dt

            # --- 2. Deviation Impact (Hybrid Correction) ---
            # We integrate the DEVIATION slope, not the absolute slope.
            # This effectively "rotates" the physics curve to match reality at t=0, 
            # and fades the rotation out over 'momentum_duration'.
            
            dev_val_at_t = 0.0
            if deviation_slope != 0:
                dt_eff = min(t, momentum_duration)
                if dt_eff > 0:
                    # Integral of decaying slope
                    dev_val_at_t = deviation_slope * dt_eff - (deviation_slope * (dt_eff**2) / (2 * momentum_duration))

            # Combine
            net_bg = current_bg + dev_val_at_t + accum_insulin_impact + accum_carb_impact + accum_basal_impact
            
            # Sanity Limits
            net_bg = max(20, min(600, net_bg))
            
            series.append(ForecastPoint(t_min=t, bg=round(net_bg, 1)))
            components.append(ComponentImpact(
                t_min=t,
                insulin_impact=round(accum_insulin_impact, 1),
                carb_impact=round(accum_carb_impact, 1),
                basal_impact=round(accum_basal_impact, 1),
                momentum_impact=round(dev_val_at_t, 1) # This is now "Deviation Impact"
            ))
            
        
        # 5. Summary
        bg_values = [p.bg for p in series]
        min_bg = min(bg_values)
        max_bg = max(bg_values)
        ending_bg = bg_values[-1]
        
        # Helper to find bg at specific time
        def get_bg_at(min_target):
            try:
                idx = time_points.index(min_target)
                return bg_values[idx]
            except:
                return None
                
        # Find time to min
        min_idx = bg_values.index(min_bg)
        time_to_min = time_points[min_idx]
        
        summary = ForecastSummary(
            bg_now=current_bg,
            bg_30m=get_bg_at(30),
            bg_2h=get_bg_at(120),
            bg_4h=get_bg_at(240),
            min_bg=round(min_bg, 0),
            max_bg=round(max_bg, 0),
            time_to_min=time_to_min,
            ending_bg=round(ending_bg, 0)
        )
        
        return ForecastResponse(
            series=series,
            components=components,
            summary=summary,
            quality=quality,
            warnings=warnings
        )
    
    @staticmethod
    def _calculate_momentum(bg_series: List[dict], lookback_points: int) -> Tuple[float, List[str]]:
        """
        Calculate linear regression slope of recent points.
        bg_series expected: [{'minutes_ago': 0, 'value': 100}, ...]
        """
        warnings = []
        if not bg_series or len(bg_series) < 3:
            warnings.append("Datos insuficientes para inercia")
            return 0.0, warnings

        # Filter relevant points
        points = []
        for p in bg_series:
            t = -1 * abs(p.get('minutes_ago', 0)) # t must be negative (past)
            v = p.get('value')
            if v is not None:
                points.append((t, v))
                
        # Guardrails
        if len(points) < lookback_points:
            # Not enough points
            return 0.0, ["Datos insuficientes para calcular tendencia (se requieren más datos recientes)"]
            
        # Sort by time
        points.sort(key=lambda x: x[0])
        
        # Check gaps
        for i in range(1, len(points)):
            if (points[i][0] - points[i-1][0]) > 15: # Gap > 15 min
                return 0.0, ["Se detectó un hueco en los datos de glucosa (tendencia desactivada)"]
                
        # Use last N points
        use_points = points[-lookback_points:]
        
        # Simple Linear Regression (Least Squares)
        n = len(use_points)
        sum_x = sum(p[0] for p in use_points)
        sum_y = sum(p[1] for p in use_points)
        sum_xy = sum(p[0]*p[1] for p in use_points)
        sum_xx = sum(p[0]**2 for p in use_points)
        
        denominator = (n * sum_xx - sum_x**2)
        if denominator == 0:
            return 0.0, ["Error matemático al calcular tendencia (denominador cero)"]
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        
        # Cap slope
        MAX_SLOPE = 3.0 # mg/dL per min
        if abs(slope) > MAX_SLOPE:
            warnings.append(f"Inercia limitada por seguridad (era {slope:.2f})")
            slope = MAX_SLOPE if slope > 0 else -MAX_SLOPE
            
        return slope, warnings
