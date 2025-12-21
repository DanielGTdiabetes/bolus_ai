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
            if "insufficient_data" in str(m_warnings) or "gap" in str(m_warnings):
                quality = "medium"
        
        # Decay momentum over time (linear 30 mins or exponential?)
        # Loop standard is usually ~30 mins decay.
        # We will decay it linearly to 0 over 30 mins to avoid long-term drift errors.
        momentum_duration = 30 
        
        # 3. Main Simulation Loop
        
        # We simulate "Changes" from t=0.
        # Forecast[t] = StartBG + Sum(Deltas)
        # Delta sources: 
        #   - Insulin (Drop)
        #   - Carbs (Rise)
        #   - Basal (Drift specific to MDI models)
        #   - Momentum (Initial drift)
        
        # To do this efficiently, we calculate absolute impact at time T rather than integrating steps?
        # Actually, curves return "Activity" (rate) or "Fraction Consumed"?
        # Our curves return "Activity Rate" (%/min) or "Absorbed/min".
        # So Delta_BG_per_min = Rate * Sensitivity.
        
        # Pre-calc totals
        icr = req.params.icr # g/U
        isf = req.params.isf # mg/dL/U
        
        # Convert ISF/ICR to useful factors
        # Carb Sensitivity (CS) = ISF / ICR  (mg/dL per gram)
        cs = isf / icr if icr > 0 else 0
        
        # 4. Iterate
        
        for t in time_points:
            
            # --- A. Momentum Impact ---
            # Integrated slope up to time t
            # If slope is M (mg/dL/min), impact at time t is Integral(M(t)).
            # If we decay M linearly from M_0 to 0 over 30 min:
            # Impact[t] = Area under triangle/trapezoid up to t.
            mom_impact = 0.0
            if momentum_slope != 0:
                dt_eff = min(t, momentum_duration)
                if dt_eff > 0:
                    # Average slope over [0, dt_eff]
                    # Slope at 0 = M
                    # Slope at 30 = 0
                    # Slope at t = M * (1 - t/30)
                    
                    # Integral of linear function: M*t - M*t^2/(2*D)
                    mom_impact = momentum_slope * dt_eff - (momentum_slope * (dt_eff**2) / (2 * momentum_duration))
                    
            # --- B. Insulin Impact (Bolus) ---
            # Sum of all boluses active at t
            # Impact = Units * ISF * fraction_absorbed(t)
            # Wait, curves.exponential_activity returns RATE (/min).
            # We need Cumulative Fraction for impact calculation?
            # Or we sum rates and integrate?
            # Easier: Calculate Cumulative Activity explicitly or sum up rates step-by-step.
            # Let's sum rates step-by-step to be safe and allow dynamic changes.
            # Actually, for performance and robustness, Cumulative Fraction is better.
            # But our `curves.py` returned activity rate.
            # Let's integrate numerically since step is small (5 min).
            pass
            
            # RE-DESIGN: Better to accumulate changes step-by-step
        
        # RE-START LOOP with State Accumulation approach
        current_sim_bg = current_bg
        
        # Initial State
        series.append(ForecastPoint(t_min=0, bg=current_sim_bg))
        components.append(ComponentImpact(t_min=0))
        
        prev_t = 0
        
        # We need to track cumulative absorption to avoid recalculating everything
        # Actually, stateless calculation at each T is more robust against drift errors *if* we have analytical integrals.
        # But step-wise integration is easier to debug.
        # Let's do Step-wise (Riemann sum).
        
        sim_bg = current_bg + mom_impact # Start with instant momentum shift? No, momentum builds up.
        
        # Let's iterate steps 1..N
        # Value at t is Value at t-1 + Rate * dt
        
        accum_insulin_impact = 0.0
        accum_carb_impact = 0.0
        accum_basal_impact = 0.0
        
        # For momentum, we already have analytical formula above (mom_impact).
        
        for i in range(1, len(time_points)):
            t = time_points[i]
            prev_t = time_points[i-1]
            dt = t - prev_t
            
            # Midpoint for better accuracy?
            t_mid = (t + prev_t) / 2.0
            
            # 1. Insulin Rate (mg/dL per minute DROP)
            # Sum of all boluses
            total_insulin_activity = 0.0 # U/min
            for b in req.events.boluses:
                # Time relative to bolus start
                # t_mid is minutes from NOW. 
                # Bolus was at b.time_offset_min (e.g. -10).
                # So time since injection = t_mid - b.time_offset_min
                t_since_inj = t_mid - b.time_offset_min
                rate = InsulinCurves.linear_activity(
                    t_since_inj, 
                    req.params.insulin_peak_minutes, 
                    req.params.dia_minutes
                )
                total_insulin_activity += rate * b.units
                
            insulin_drop_rate = total_insulin_activity * isf
            step_insulin_drop = insulin_drop_rate * dt
            accum_insulin_impact -= step_insulin_drop
            
            # 2. Carb Rate (mg/dL per minute RISE)
            step_carb_impact_rate = 0.0 # mg/dL / min
            
            for c in req.events.carbs:
                t_since_meal = t_mid - c.time_offset_min
                dur = c.absorption_minutes or req.params.carb_absorption_minutes
                # Linear absorption (trapezoidal in future?)
                # Let's use variable/triangle for better realism?
                rate = CarbCurves.variable_absorption(t_since_meal, dur, peak_min=dur/2) # Fraction / min
                
                # Determine CS (Carb Sensitivity) for this specific carb event
                # Use event-specific ICR if available, otherwise global simulation param
                this_icr = c.icr if c.icr and c.icr > 0 else req.params.icr
                
                # CS = ISF / ICR
                this_cs = (req.params.isf / this_icr) if this_icr > 0 else 0.0
                
                step_carb_impact_rate += rate * c.grams * this_cs
                
            step_carb_rise = step_carb_impact_rate * dt
            accum_carb_impact += step_carb_rise
            
            # 3. Momentum
            # Recalculate analytical impact at t
            dt_eff = min(t, momentum_duration)
            mom_val_at_t = 0
            if req.momentum and req.momentum.enabled and momentum_slope != 0 and dt_eff > 0:
                 mom_val_at_t = momentum_slope * dt_eff - (momentum_slope * (dt_eff**2) / (2 * momentum_duration))
            
            # 4. Basal Impact (Drift)
            # Calculate deviation from "neutral" (if we assume basal keeps you flat)
            # If user provides Basal Injections, we model their activity.
            # But what is the baseline? 
            # Usually: "Basal covers liver output".
            # So effectively, Basal Activity should cancel Liver Output.
            # If we model Basal Activity, we must also model Liver Output (positive drift).
            # This is complex.
            # ALTERNATIVE: MDI Basal Injections are usually to check for "Stacking" or "Running out".
            # Loop assumes Basal = Scheduled Basal returns NET ZERO.
            # For MDI, if we inject specific basal, maybe we assume the User wants to see its curve?
            # Or maybe we assume Liver Output is constant = Total Daily Basal / 24 * ISF ?
            # Let's assume:
            # Baseline Drift = (Total Daily Basal / 1440) * ISF (Positive constant rise).
            # Basal Injection = Curve (Negative drop).
            # Net = Baseline - Injection.
            # Ideally they cancel out.
            
            accum_basal_val = 0.0
            # Only calculate if basal injections are provided, otherwise assume flat
            if req.events.basal_injections:
                # Estimate Liver/Baseline requirement
                # Sum total daily basal from injections? Or just assume current profile?
                # Let's keep it simple: Just show the Insulin Drop from the injection.
                # The user mentally knows they have liver output.
                # OR: Be smart. Calculate average rate around t=0 (now) and normalize to 0?
                # "Relative Basal Effect".
                # If at t=0, basal is delivering 1U/hr, and at t=100 it delivers 0.5U/hr.
                # Then user is missing 0.5U/hr -> Glucose rises.
                # This is the "Basal IOB" concept.
                
                # Let's implement "Relative to t=0".
                # Calculate Basal Rate at t=0.
                rate_at_0 = 0.0
                for b in req.events.basal_injections:
                    t_since = 0 - b.time_offset_min
                    rate_at_0 += BasalModels.get_activity(t_since, b.duration_minutes or 1440, b.type, b.units)
                
                # Calculate Rate at t
                rate_at_t = 0.0
                for b in req.events.basal_injections:
                    t_since = t_mid - b.time_offset_min
                    rate_at_t += BasalModels.get_activity(t_since, b.duration_minutes or 1440, b.type, b.units)
                
                # Net Drift Rate = (Rate_at_0 - Rate_at_t) * ISF
                # If rate drops (old insulin fading), term is positive -> Glucose Rises.
                # If rate rises (new insulin acting), term is negative -> Glucose Drops.
                
                basal_drift_rate = (rate_at_0 - rate_at_t) * isf
                accum_basal_impact += basal_drift_rate * dt

            
            # Combine
            net_bg = current_bg + mom_val_at_t + accum_insulin_impact + accum_carb_impact + accum_basal_impact
            
            # Sanity Limits
            net_bg = max(20, min(600, net_bg)) # Clamp to survive chart
            
            series.append(ForecastPoint(t_min=t, bg=round(net_bg, 1)))
            components.append(ComponentImpact(
                t_min=t,
                insulin_impact=round(accum_insulin_impact, 1),
                carb_impact=round(accum_carb_impact, 1),
                basal_impact=round(accum_basal_impact, 1),
                momentum_impact=round(mom_val_at_t, 1)
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
            return 0.0, ["puntos_insuficientes_inercia"]
            
        # Sort by time
        points.sort(key=lambda x: x[0])
        
        # Check gaps
        for i in range(1, len(points)):
            if (points[i][0] - points[i-1][0]) > 15: # Gap > 15 min
                return 0.0, ["hueco_detectado_inercia_desactivada"]
                
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
            return 0.0, ["error_matematico_inercia"]
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        
        # Cap slope
        MAX_SLOPE = 3.0 # mg/dL per min
        if abs(slope) > MAX_SLOPE:
            warnings.append(f"Inercia limitada (era {slope:.2f})")
            slope = MAX_SLOPE if slope > 0 else -MAX_SLOPE
            
        return slope, warnings
