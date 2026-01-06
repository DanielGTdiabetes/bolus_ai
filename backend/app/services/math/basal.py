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
            # Modified to "Flat" profile to prevent false Hypo predictions on injection.
            # While physiologically it has a ramp-up, mathematically comparing "Rate Now (0)" vs "Rate Future (High)" 
            # causes a massive predicted drop if the previous basal is not perfectly aligned or missing.
            # A constant rate ensures Drift = 0 (Stability), which matches user expectation for Basal.
            return total_units / duration_min
        
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
