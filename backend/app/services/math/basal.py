import math
from typing import Literal

class BasalModels:
    """
    Approximation models for Long Acting Insulin (Basal) injections.
    Returns 'Units per Minute' active at time t.
    """
    
    @staticmethod
    def get_activity(t_min: float, duration_min: float, type: str, total_units: float) -> float:
        """
        Returns units released per minute at time t since injection.
        """
        if t_min < 0 or t_min >= duration_min:
            return 0.0
            
        if type in ["degludec", "tresiba", "toujeo"]:
            # Ultra-flat. Modeled as constant 
            return total_units / duration_min
            
        if type in ["glargine", "lantus", "basaglar"]:
            # Mostly flat, slight gentle peak around 4-6h, slight taper at end.
            # For simplicity in simulation, we can model as flat or a very soft trapezoid.
            # User feedback says "MDI Basal models (flat or simple curves for Glargine)".
            # Let's use a subtle trapezoid: 
            # 0-1h: Ramp up
            # 1h - (End-4h): Flat
            # Last 4h: Ramp down
            ramp_up_min = 60
            ramp_down_min = 240
            
            # If duration is too short for this profile, fall back to flat
            if duration_min < (ramp_up_min + ramp_down_min):
                return total_units / duration_min
                
            plateau_duration = duration_min - ramp_up_min - ramp_down_min
            
            # Calculate height (h) such that Area = Total Units
            # Area = (1/2 * ramp_up * h) + (plateau * h) + (1/2 * ramp_down * h)
            # Area = h * (0.5*60 + plateau + 0.5*240)
            # h = Units / (...)
            
            denom = (0.5 * ramp_up_min) + plateau_duration + (0.5 * ramp_down_min)
            h = total_units / denom
            
            if t_min < ramp_up_min:
                return h * (t_min / ramp_up_min)
            elif t_min < (ramp_up_min + plateau_duration):
                return h
            else:
                remaining = duration_min - t_min
                return h * (remaining / ramp_down_min)
        
        if type in ["detemir", "levemir"]:
            # Distinct peak around 6-8h, shorter tail.
            # Simplified parabolic or triangle approximation.
            return (total_units / duration_min) # Start with flat for safety unless requested precise
            
        if type in ["nph", "isophane"]:
            # Strong peak at 6-8 hours.
            # Triangle approximation.
            peak_time = duration_min * 0.4 # Peak at ~40% of duration (e.g. 6-7h of 18h)
            h = 2 * total_units / duration_min
            
            if t_min < peak_time:
                return h * (t_min / peak_time)
            else:
                return h * ((duration_min - t_min) / (duration_min - peak_time))

        # Default Custom/Other: Flat
        return total_units / duration_min
