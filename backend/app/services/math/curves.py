import math

class InsulinCurves:
    """
    Standard insulin activity models.
    All functions return the *Activity Percentage* (0.0 to 1.0) or *Cumulative Activity* 
    depending on the method.
    """
    
    @staticmethod
    def _walsh_tau(peak_min, duration_min):
        if duration_min <= 0: return 0
        denom = 1 - 2 * peak_min / duration_min
        if denom == 0: return 0
        return peak_min * (1 - peak_min / duration_min) / denom

    @staticmethod
    def _walsh_F(t, duration, tau):
        # Antiderivative of raw curve (1-t/D)*exp(-t/tau)
        if tau == 0: return 0
        term = (tau/duration) - 1 + (t/duration)
        return tau * math.exp(-t/tau) * term

    @staticmethod
    def exponential_activity(t_min: float, peak_min: float, duration_min: float) -> float:
        """
        Calculates the instantaneous activity (percent of total dose / min).
        Normalized so that total area under curve equals 1.0.
        """
        if t_min <= 0 or t_min >= duration_min:
            return 0.0
            
        tau = InsulinCurves._walsh_tau(peak_min, duration_min)
        if tau <= 0:
             return InsulinCurves.linear_activity(t_min, peak_min, duration_min)

        # Normalize by Area
        F0 = InsulinCurves._walsh_F(0, duration_min, tau)
        FD = InsulinCurves._walsh_F(duration_min, duration_min, tau)
        area = FD - F0
        if area == 0: return 0.0

        raw = (1 - t_min / duration_min) * math.exp(-t_min / tau)
        return raw / area

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



    @staticmethod
    def get_activity(t_min: float, duration_min: float, peak_min: float, model_type: str) -> float:
        """
        Unified accessor.
        Uses standard Exponential / Walsh model for all types, varying parameters.
        """
        m = model_type.lower()
        if m == 'fiasp':
            return InsulinCurves.exponential_activity(t_min, 55, duration_min)
        elif m == 'novorapid':
            return InsulinCurves.exponential_activity(t_min, 75, duration_min)
        elif m == 'exponential' or m == 'walsh':
            return InsulinCurves.exponential_activity(t_min, peak_min, duration_min)
        else:
            return InsulinCurves.linear_activity(t_min, peak_min, duration_min)

    @staticmethod
    def exponential_iob(t_min: float, peak_min: float, duration_min: float) -> float:
        """
        Fraction of insulin remaining.
        Calculated as (TotalArea - CumulativeArea) / TotalArea.
        """
        if t_min <= 0: return 1.0
        if t_min >= duration_min: return 0.0
        
        tau = InsulinCurves._walsh_tau(peak_min, duration_min)
        if tau <= 0:
            return max(0.0, 1.0 - t_min / duration_min)
            
        F0 = InsulinCurves._walsh_F(0, duration_min, tau)
        FD = InsulinCurves._walsh_F(duration_min, duration_min, tau)
        Ft = InsulinCurves._walsh_F(t_min, duration_min, tau)
        
        denom = FD - F0
        if denom == 0: return 0.0
        return (FD - Ft) / denom

    @staticmethod
    def get_iob(t_min: float, duration_min: float, peak_min: float, model_type: str) -> float:
        m = model_type.lower()
        if m == 'fiasp':
            return InsulinCurves.exponential_iob(t_min, 55, duration_min)
        elif m == 'novorapid':
            return InsulinCurves.exponential_iob(t_min, 75, duration_min)
        elif m == 'exponential' or m == 'walsh':
            return InsulinCurves.exponential_iob(t_min, peak_min, duration_min)
        else:
            return max(0.0, 1.0 - t_min / duration_min)

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
