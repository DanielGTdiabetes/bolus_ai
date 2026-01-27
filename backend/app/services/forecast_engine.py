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
             
             if c.fiber_g > 0 or c.fat_g > 0 or c.protein_g > 0:
                 params = CarbCurves.get_biexponential_params(c.grams, c.fiber_g, c.fat_g, c.protein_g)
                 r = CarbCurves.biexponential_absorption(t_since, params)
             else:
                dur = c.absorption_minutes or req.params.carb_absorption_minutes
                peak = c.absorption_peak_min or (dur / 2 if dur else 60)
                if not c.absorption_minutes and c.absorption_peak_min and c.absorption_tail_min:
                    dur = c.absorption_peak_min + c.absorption_tail_min
                shape = (c.absorption_shape or "triangle").lower()
                if shape == "linear":
                    r = CarbCurves.linear_absorption(t_since, dur)
                elif shape == "biexponential":
                    params = {
                        "f": 0.6,
                        "t_max_r": peak,
                        "t_max_l": max(peak + (c.absorption_tail_min or peak), peak * 2),
                    }
                    r = CarbCurves.biexponential_absorption(t_since, params)
                else:
                    r = CarbCurves.variable_absorption(t_since, dur, peak_min=peak)
             # Resolve CS
             this_icr = c.icr if c.icr and c.icr > 0 else req.params.icr
             this_cs = (req.params.isf / this_icr) if this_icr > 0 else 0.0
             carb_rate_0 += r * c.grams * this_cs
             
        # Net Model Slope (mg/dL per min)
        # Insulin drops (negative), Carbs rise (positive)
        # ins_rate_0 is U/min. Mult by ISF -> mg/dL/min.
        isf = req.params.isf
        # Basal Slope at t=0 (Absolute Model)
        basal_rate_0 = 0.0
        if req.events.basal_injections:
            for b in req.events.basal_injections:
                t_since = 0 - b.time_offset_min
                basal_rate_0 += BasalModels.get_activity(t_since, b.duration_minutes or 1440, b.type, b.units)
        
        reference_rate = 0.0
        if req.params.basal_daily_units > 0:
             reference_rate = req.params.basal_daily_units / 1440.0
             
        net_basal_activity = basal_rate_0 - reference_rate

        # Net Model Slope (mg/dL per min)
        # Insulin drops (negative), Carbs rise (positive)
        # ins_rate_0 is U/min. Mult by ISF -> mg/dL/min.
        isf = req.params.isf
        model_slope_0 = carb_rate_0 - ((ins_rate_0 + net_basal_activity) * isf)
        
        # B. Calculate Deviation Slope (The "Unknown Force")
        # Deviation = Observed - Model
        # If Observed=-5, Model=-1 (just starting), Deviation = -4 (Resistance/Error or Momentum)
        deviation_slope = 0.0
        if req.momentum and req.momentum.enabled and momentum_slope != 0:
            deviation_slope = momentum_slope - model_slope_0
            
            # Dampening: Increase from 1.5 to 3.5 to trust real-world drift more (User reports)
            if abs(deviation_slope) > 3.5:
                 warnings.append(f"Desviación masiva detectada ({deviation_slope:.1f}), amortiguada.")
                 deviation_slope = 3.5 if deviation_slope > 0 else -3.5
                 quality = "medium"

        # Increase momentum influence duration for smoother blending (~30 mins)
        # Reduced from 45 to 30 to limit projection of short-term noise
        momentum_duration = 30 

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
            
            # Apply Sensitivity Multiplier (Resistance)
            # Default to 1.0 (Full Efficacy) if None
            sens_multiplier = req.params.insulin_sensitivity_multiplier if req.params.insulin_sensitivity_multiplier is not None else 1.0
            
            step_insulin_drop = total_insulin_activity * isf * dt * sens_multiplier
            accum_insulin_impact -= step_insulin_drop
            
            # Carbs
            step_carb_impact_rate = 0.0
            
            # Metadata for absorption tracking
            # Usually there's only one main carb event in these simulations.
            chosen_profile = "none"
            chosen_confidence = "low"
            chosen_reasons = []

            for c in req.events.carbs:
                t_since_meal = t_mid - c.time_offset_min
                
                # Selection of Carb Model
                profile_res = ForecastEngine._decide_absorption_profile(c)
                
                # If multiple carb events, we take the dominant one (latest/biggest) for reporting metadata
                if chosen_profile == "none" or (c.grams > 10 and t_since_meal < 60):
                    chosen_profile = profile_res["profile"]
                    chosen_confidence = profile_res["confidence"]
                    chosen_reasons = profile_res["reasons"]

                # --- PROTEIN/FAT IMPACT ---
                # We need to account for the glucose-conversion of Protein and Fat (FPU).
                # If we don't, the simulator sees massive insulin (dosed for F/P) vs tiny carbs -> False Hypo.
                # Approx: 100kcal of F/P ~= 10g Carbs (Warsaw Method standard).
                
                effective_grams = c.grams
                
                # --- FIBER DEDUCTION ---
                # Subtract fiber from "Fast" carbs if enabled
                if req.params.use_fiber_deduction and c.fiber_g > req.params.fiber_threshold and effective_grams > 0:
                    deduction = c.fiber_g * req.params.fiber_factor
                    effective_grams = max(0.0, effective_grams - deduction)
                    
                    if chosen_profile == profile_res["profile"] and deduction > 0.5:
                         chosen_reasons.append(f"-{deduction:.1f}g Fibra")

                # Check if F/P data exists
                if c.fat_g > 0 or c.protein_g > 0:
                    kcal_from_fp = (c.fat_g * 9) + (c.protein_g * 4)
                    # Only apply if significant (>50 kcal) to avoid noise
                    if kcal_from_fp > 50:
                        # Convert to equivalent grams (eCarbs) using Warsaw Setting
                        # Formula: (Kcal / 100) * 10 * Factor
                        # Factor 1.0 => 100kcal = 10g eCarbs.
                        # Factor 0.5 => 100kcal = 5g eCarbs (Safety).
                        
                        # Hotfix: Normalize w_factor
                        w = req.params.warsaw_factor_simple
                        if w is None or w <= 0:
                            w = 0.1
                        w_factor = w
                        fpu_count = kcal_from_fp / 100.0
                        fpu_grams = fpu_count * 10.0 * w_factor
                        
                        effective_grams += fpu_grams
                        
                        # Add a note to reasons if it is the primary meal
                        if chosen_profile == profile_res["profile"] and "eCarbs" not in "".join(chosen_reasons):
                            chosen_reasons.append(f"+{fpu_grams:.1f}g eCarbs (Warsaw x{w_factor})")

                # --- AUTO-HARMONIZATION (Trust the Bolus) ---
                # If the user delivered a Bolus that is significantly higher than what minimal carbs require,
                # we assume the "surplus" is covering the Fat/Protein. We adjust the effective_grams to match the dose.
                # This prevents the graph from contradicting the Bolus Calculator.
                
                this_icr = c.icr if c.icr and c.icr > 0 else req.params.icr
                this_cs = (req.params.isf / this_icr) if this_icr > 0 else 0.0
                
                # 1. Find linked bolus for this meal (Widen to 90 min)
                linked_bolus_u = 0.0
                for b in req.events.boluses:
                    if abs(b.time_offset_min - c.time_offset_min) <= 90:
                        linked_bolus_u += b.units

                if linked_bolus_u > 0:
                    # 2. Calculate Correction Component (Rough estimate)
                    bg_at_meal = current_bg 
                    
                    this_icr = c.icr if c.icr and c.icr > 0 else req.params.icr
                    if this_icr > 0:
                        implied_total_grams = linked_bolus_u * this_icr
                        
                        target_val = req.params.target_bg
                        excess_bg = max(0, current_bg - target_val)
                        correction_penalty_grams = (excess_bg / isf * this_icr) if isf > 0 else 0
                        
                        available_meal_grams = implied_total_grams - correction_penalty_grams
                        
                        # If the Bolus covers MORE than (Carbs + Calculated FPU), we upgrade the FPU.
                        if available_meal_grams > effective_grams * 1.1: # 10% tolerance
                            # The user dosed for MORE.
                            # Check if we have ample Fat/Protein to justify it.
                            kcal_fp = (c.fat_g * 9) + (c.protein_g * 4)
                            # ALWAYS allow harmonization if F/P exists, even if small, up to a generous cap.
                            # We trust the bolus over the heuristics if F/P provides a material basis.
                            if kcal_fp > 10: # Relaxed from 50
                                # Attribute the difference to FPU
                                diff_grams = available_meal_grams - effective_grams
                                
                                # Cap: Don't allow creating matter out of thin air.
                                # Max theoretical eCarbs from FPU is usually Kcal/10 (Factor 1.0)
                                max_fpu_grams = kcal_fp / 10.0
                                
                                # If we have room to grow FPU
                                # Increase tolerance to 5.0x to handle aggressive factor 1.0 logic
                                if (effective_grams + diff_grams) <= (c.grams + max_fpu_grams * 6.0): 
                                    reasons_append = f" (+{diff_grams:.1f}g Auto-Ajuste por Bolo)"
                                    if chosen_profile == profile_res["profile"]:
                                        chosen_reasons.append(reasons_append)
                                    effective_grams += diff_grams
                                    
                                    # TIMING ADJUSTMENT:
                                    # If we harmonized significantly against a bolus, and profile is SLOW,
                                    # it creates a "False Hypo" because standard bolus is Fast.
                                    # We assume user knows what they are doing (Simple Bolus) -> accelerate curve.
                                    if profile_res["profile"] == "slow":
                                         profile_res["profile"] = "med"
                                         chosen_profile = "med"
                                         if chosen_profile == profile_res["profile"]:
                                              chosen_reasons.append(" (Acerelado por Bolo)")

                                else:
                                    # Overdose detected (Surplus > Capacity)
                                    top_cap = c.grams + max_fpu_grams * 6.0
                                    warning_msg = f"Auditoría: Bolo ({linked_bolus_u}U) excede capacidad de absorción ({top_cap:.0f}g est.)."
                                    if warning_msg not in warnings:
                                        warnings.append(warning_msg)

                # Calculate Rate with FINAL profile and grams
                # MODIFICACIÓN: Usamos el modelo dinámico basado en GRASA (Opción A)
                params_curve = CarbCurves.get_dynamic_carb_params(effective_grams, c.fat_g, profile_res["profile"])
                
                # Ajuste opcional por duración (si el usuario forzó una duración distinta a la estándar de 3h)
                dur_m = c.absorption_minutes or req.params.carb_absorption_minutes or 180
                scale_f = dur_m / 180.0
                params_curve['t_max_r'] *= scale_f
                params_curve['t_max_l'] *= scale_f
                
                rate = CarbCurves.biexponential_absorption(t_since_meal, params_curve)
                
                step_carb_impact_rate += rate * effective_grams * this_cs
                
            step_carb_rise = step_carb_impact_rate * dt
            accum_carb_impact += step_carb_rise
            
            # Basal Impact (Absolute Model)
            # We compare Active Basal vs "Required" Basal (Reference).
            # If Active < Reference -> Net negative insulin -> BG Rises.
            # If Active > Reference -> Net positive insulin -> BG Drops.
            
            reference_rate = 0.0
            if req.params.basal_daily_units > 0:
                 reference_rate = req.params.basal_daily_units / 1440.0
            
            rate_at_t = 0.0
            if req.events.basal_injections:
                for b in req.events.basal_injections:
                    t_since = t_mid - b.time_offset_min
                    rate_at_t += BasalModels.get_activity(t_since, b.duration_minutes or 1440, b.type, b.units)
            
            # Impact is inverted: More insulin = Drop (-), Less = Rise (+)
            # net_insulin = (Active - Required)
            # impact = -1 * net_insulin * ISF
            drift_mode = getattr(req.params, 'basal_drift_handling', 'standard')
            if drift_mode == 'neutral':
                 step_basal_impact = 0.0
            else:
                 step_basal_impact = -1 * (rate_at_t - reference_rate) * isf * dt
            accum_basal_impact += step_basal_impact

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

            # --- 3. Advanced Anti-Panic Gating (The "Golden Rule" V2) ---
            # Replaces fixed 1-hour amortization with intelligent meal-linked gating.
            
            insulin_net = accum_insulin_impact
            carb_net = accum_carb_impact
            
            # Pre-calculate BG for safety checks (before potential damping)
            current_predicted_bg = current_bg + dev_val_at_t + insulin_net + carb_net + accum_basal_impact

            # GATING CRITERIA:
            # 1. Carbs >= threshold (10g)
            # 2. Associated bolus in +/- 15 min
            # 3. Not a pure correction (c.grams > 0)
            
            is_linked_meal = False
            linked_carbs = 0.0
            linked_bolus_u = 0.0
            
            for c in req.events.carbs:
                if c.grams >= 2: # Lower to 2g
                    for b in req.events.boluses:
                        if abs(b.time_offset_min - c.time_offset_min) <= 90: # Widen to 90
                            is_linked_meal = True
                            linked_carbs += c.grams
                            linked_bolus_u += b.units
            
            # If linked meal detected and we are in the early phase (decays over 120 mins)
            if is_linked_meal and t < 120:
                # Calculate physics-based drop
                net_drop = abs(insulin_net) - carb_net
                
                if net_drop > 0:
                    # Safety Guards: Disable damping if risks are detected
                    # A) Fast drop in simulation
                    instant_slope = (current_predicted_bg - series[-1].bg) if series else 0
                    
                    # B) Predicted BG is already low
                    is_low_risk = current_predicted_bg < 80
                    
                    # C) Reality is already dropping fast (momentum)
                    is_fast_dropping = deviation_slope < -2.5
                    
                    if not (is_low_risk or is_fast_dropping):
                        # Apply decay damping factor (1.0 at 90m, ~0.6 at start)
                        # Decays progressively to avoid sudden jumps.
                        damp_factor = 0.6 + (0.4 * (t / 90.0))
                        insulin_net *= damp_factor

            # Combine
            net_bg = current_bg + dev_val_at_t + insulin_net + carb_net + accum_basal_impact
            
            # Sanity Limits
            net_bg = max(20, min(600, net_bg))
            
            series.append(ForecastPoint(t_min=t, bg=round(net_bg, 1)))
            components.append(ComponentImpact(
                t_min=t,
                insulin_impact=round(insulin_net, 1),
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
            warnings=warnings,
            absorption_profile_used=chosen_profile,
            absorption_confidence=chosen_confidence,
            absorption_reasons=chosen_reasons,
            slow_absorption_active=(chosen_profile == "slow"),
            slow_absorption_reason=" ".join(chosen_reasons) if chosen_profile == "slow" else None
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
        MAX_SLOPE = 1.5 # mg/dL per min (Reduced from 3.0 to prevent jumpiness)
        if abs(slope) > MAX_SLOPE:
            warnings.append(f"Inercia limitada por seguridad (capped, era {slope:.2f})")
            slope = MAX_SLOPE if slope > 0 else -MAX_SLOPE
            
        return slope, warnings

    @staticmethod
    def _decide_absorption_profile(c) -> dict:
        """
        Deterministically decides the best absorption profile based on macros.
        Returns: {profile: 'fast'|'med'|'slow', confidence: 'high'|'medium'|'low', reasons: []}
        """
        # 1. Manual Override
        if c.carb_profile:
            return {
                "profile": c.carb_profile,
                "confidence": "high",
                "reasons": ["Selección manual del usuario"]
            }
        
        # 2. Heuristics
        reasons = []
        profile = "med"
        confidence = "low"
        
        if c.grams <= 0:
            return {"profile": "none", "confidence": "high", "reasons": []}
            
        fat_protein = c.fat_g + c.protein_g
        
        # Rule B: Fats + Protein high => Slow
        # REFINED: Experienced users report 30g is too low threshold for 6h absorption.
        # We bump "Slow" (Long tail) to > 60g (Heavy meals).
        # We keep "Med" (Standard 3-4h) for 20-60g.
        
        if fat_protein > 60: # Multi-hour delay sign (Heavy Pizza/Burger)
            profile = "slow"
            confidence = "high"
            reasons.append(f"Grasas+Proteínas muy altas ({fat_protein}g)")
        elif fat_protein > 20: 
            # Changed from profile="slow" to "med" to avoid late-rise ghosts on normal meals
            profile = "med"
            confidence = "medium"
            reasons.append(f"Grasas+Proteínas ({fat_protein}g)")
            
        # Rule C: Fiber high => Slow/Medium modifier
        if c.fiber_g >= c.grams and c.grams > 0:
            profile = "slow"
            confidence = "high"
            reasons.append(f"Fibra Alta ({c.fiber_g}g >= {c.grams}g) -> Absorción Lenta")
        elif c.fiber_g > 10:
            profile = "slow"
            confidence = "high"
            reasons.append(f"Fibra muy alta ({c.fiber_g}g)")
        elif c.fiber_g > 5 and profile == "med":
            profile = "med" # Stays medium but adds confidence
            confidence = "medium"
            reasons.append(f"Fibra ({c.fiber_g}g)")

        # Rule E: Dessert Mode (Fast sugar)
        if getattr(c, 'is_dessert', False):
            profile = "fast"
            confidence = "high"
            reasons.insert(0, "Modo Microbolos (Azúcares rápidos)")

        # Rule D: Liquid sugars (Placeholder - typically would come from a 'tags' field or food name)
        # For now, if carbs > 0 and everything else is 0, we treat it as faster than normal if it's small, 
        # but standard "med" is safer for "No Info".
        
        if not reasons:
            profile = "med"
            confidence = "low"
            reasons.append("Sin información adicional de macros")
            
        return {
            "profile": profile,
            "confidence": confidence,
            "reasons": reasons
        }
