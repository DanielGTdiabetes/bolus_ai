import math

class InsulinCurves:
    """
    Standard insulin activity models.
    All functions return the *Activity Percentage* (0.0 to 1.0) or *Cumulative Activity* 
    depending on the method.
    """
    
    @staticmethod
    def exponential_activity(t_min: float, peak_min: float, duration_min: float) -> float:
        """
        Calculates the instantaneous activity (percent of total dose / min)
        Based on a simplified Dr. Walsh / Loop exponential model approximation.
        This describes 'how strong' the insulin is working at time t.
        Integration of this curve over [0, duration] should sum to ~1.0 (100% absorption).
        """
        if t_min <= 0 or t_min >= duration_min:
            return 0.0
            
        # Time constants derived from Peak and Duration
        # Model: A * t * exp(-t / tau) 
        # But for simplicity/robustness without complex fitting, we use 
        # a Walsh-style monophasic curve approximation.
        
        # Standard Walsh model:
        # activity = scale * (t / tau) * (1 - t/T_end) / (1 + t/tau_2) ... 
        # Let's use the simplest robust "Walsh" implementation found in open source Loop docs:
        
        tau = peak_min * (1 - peak_min / duration_min) / (1 - 2 * peak_min / duration_min)
        a = 2 * tau / duration_min
        S = 1 / (1 - a + (1 + a) * math.exp(-duration_min / tau))
        
        if tau <= 0: # Fallback if peak/duration parameters are invalid
             # Linear fallback
             if t_min < peak_min: 
                 return (t_min / peak_min) * (2/duration_min) 
             else:
                 return ((duration_min - t_min) / (duration_min - peak_min)) * (2/duration_min)

        activity = (S / tau) * (1 - t_min / duration_min) * math.exp(-t_min / tau)
        return max(0.0, activity)

    @staticmethod
    def linear_activity(t_min: float, peak_min: float, duration_min: float) -> float:
        """
        Simple bilinear triangle. 
        Peak is normalized such that Area = 1.0
        Height H = 2 / Duration
        """
        if t_min <= 0 or t_min >= duration_min:
            return 0.0
            
        h = 2.0 / duration_min
        
        if t_min < peak_min:
            return h * (t_min / peak_min)
        else:
            return h * ((duration_min - t_min) / (duration_min - peak_min))


class CarbCurves:
    """
    Carb absorption models.
    Returns grams absorbed per minute (fraction) or similar.
    """
    
    @staticmethod
    def linear_absorption(t_min: float, duration_min: float) -> float:
        """
        Constant absorption over duration (Square wave).
        Simple but effective for general approximation.
        """
        if t_min <= 0 or t_min >= duration_min:
            return 0.0
        return 1.0 / duration_min

    @staticmethod
    def variable_absorption(t_min: float, duration_min: float, peak_min: float = 60) -> float:
        """
        Triangle absorption (Bilinear).
        """
        if t_min <= 0 or t_min >= duration_min:
            return 0.0
            
        h = 2.0 / duration_min
        if t_min < peak_min:
             return h * (t_min / peak_min)
        else:
             return h * ((duration_min - t_min) / (duration_min - peak_min))
