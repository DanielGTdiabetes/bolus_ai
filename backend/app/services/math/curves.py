
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
             return InsulinCurves.bilinear_activity(t_min, peak_min, duration_min)

        # Normalize by Area
        F0 = InsulinCurves._walsh_F(0, duration_min, tau)
        FD = InsulinCurves._walsh_F(duration_min, duration_min, tau)
        area = FD - F0
        if area == 0: return 0.0

        raw = (1 - t_min / duration_min) * math.exp(-t_min / tau)
        return raw / area

    @staticmethod
    def bilinear_activity(t_min: float, peak_min: float, duration_min: float) -> float:
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
    def bilinear_iob(t_min: float, peak_min: float, duration_min: float) -> float:
        """
        IOB for Bilinear (Triangle) Activity.
        Analytical integral of the Triangle function.
        Total Area = 1.0.
        IOB = 1.0 - Cumulative Area.
        """
        if t_min <= 0: return 1.0
        if t_min >= duration_min: return 0.0
        
        h = 2.0 / duration_min
        consumed = 0.0
        
        if t_min < peak_min:
            # Triangle area up to t: 0.5 * base * height_at_t
            # height_at_t = h * (t / peak)
            current_h = h * (t_min / peak_min)
            consumed = 0.5 * t_min * current_h
        else:
            # Full first triangle + partial second
            # Area 1 (up to peak) = 0.5 * peak * h
            area1 = 0.5 * peak_min * h
            
            # Area 2 (trapezoid from peak to t)
            # Easier: Total Area (1.0) - Remaining Triangle
            # Remaining triangle base = duration - t
            # Remaining height = h * (duration - t) / (duration - peak)
            rem_base = duration_min - t_min
            rem_height = h * (rem_base / (duration_min - peak_min))
            rem_area = 0.5 * rem_base * rem_height
            
            consumed = 1.0 - rem_area

        return max(0.0, 1.0 - consumed)

    @staticmethod
    def get_activity(t_min: float, duration_min: float, peak_min: float, model_type: str) -> float:
        """
        Unified accessor.
        Using Bilinear for Fiasp/NovoRapid to properly model the startup delay (0->Peak).
        """
        m = model_type.lower()
        if m in ['fiasp', 'novorapid', 'bilinear', 'triangle']:
            # Using configured peak (e.g. 55 or 75)
            # Note: We hardcoded peaks inside here previously. 
            # Now we prefer passed peak_min, but for fiasp/novo specific keys we force accurate defaults if peak_min is generic.
            
            # If function called with generic peak but model is specific, override?
            # The caller usually passes settings.peak_min.
            # If model is 'fiasp', we want 55. If 'novorapid', 75.
            p = peak_min
            if m == 'fiasp': p = 55
            if m == 'novorapid': p = 75
            
            return InsulinCurves.bilinear_activity(t_min, p, duration_min)
            
        elif m == 'exponential' or m == 'walsh':
            return InsulinCurves.exponential_activity(t_min, peak_min, duration_min)
        else:
            return InsulinCurves.bilinear_activity(t_min, peak_min, duration_min)

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
        
        # Use Data-Driven Curves for Fiasp/NovoRapid if exact match
        if m == 'fiasp':
            return InterpolatedCurves.get_iob('fiasp', t_min, duration_min)
        elif m == 'novorapid':
            return InterpolatedCurves.get_iob('novorapid', t_min, duration_min)

        # Fallback to Math Models for others
        if m in ['bilinear', 'triangle']:
            return InsulinCurves.bilinear_iob(t_min, peak_min, duration_min)
        elif m == 'exponential' or m == 'walsh':
            return InsulinCurves.exponential_iob(t_min, peak_min, duration_min)
        else:
            return max(0.0, 1.0 - t_min / duration_min)

    @staticmethod
    def get_activity(t_min: float, duration_min: float, peak_min: float, model_type: str) -> float:
        m = model_type.lower()
        if m == 'fiasp':
            return InterpolatedCurves.get_activity('fiasp', t_min, duration_min)
        elif m == 'novorapid':
            return InterpolatedCurves.get_activity('novorapid', t_min, duration_min)
            
        if m in ['bilinear', 'triangle']:
            return InsulinCurves.bilinear_activity(t_min, peak_min, duration_min)
        elif m == 'exponential' or m == 'walsh':
            return InsulinCurves.exponential_activity(t_min, peak_min, duration_min)
        else:
             return InsulinCurves.bilinear_activity(t_min, peak_min, duration_min)


class InterpolatedCurves:
    """
    Data-driven curves based on EMA/EPAR clinical studies (GIR).
    Source: User provided (Fiasp: 445421/2016, NovoRapid: 3211/2005)
    """
    
    # Data points: (time_min, activity_pct)
    _DATA = {
        'fiasp': [
            (0, 0), (15, 8), (30, 25), (45, 50), (60, 75), 
            (75, 90), (90, 98), (105, 100), (120, 95), (135, 88),
            (150, 78), (165, 65), (180, 50), (195, 38), (210, 28),
            (225, 20), (240, 12), (255, 7), (270, 3), (285, 1), (300, 0)
        ],
        'novorapid': [
            (0, 0), (15, 0), (30, 12), (45, 28), (60, 50), 
            (75, 70), (90, 85), (105, 95), (120, 100), (135, 98),
            (150, 90), (165, 80), (180, 65), (195, 50), (210, 38),
            (225, 28), (240, 18), (255, 10), (270, 5), (285, 2), (300, 0)
        ]
    }
    
    _CACHE = {} # Stores (total_area, cdf_points)

    @classmethod
    def _ensure_cache(cls, key: str):
        if key in cls._CACHE: return
        points = cls._DATA.get(key)
        if not points: return # Should not happen if key valid
        
        # Calculate Total Area and CDF (Cumulative Area)
        # Using Trapezoidal Rule
        total_area = 0.0
        cdf = [(0, 0.0)] # (time, cumulative_area)
        
        for i in range(1, len(points)):
            t0, y0 = points[i-1]
            t1, y1 = points[i]
            
            # Area of trapezoid
            dt = t1 - t0
            avg_y = (y0 + y1) / 2.0
            segment_area = dt * avg_y
            
            total_area += segment_area
            cdf.append((t1, total_area))
            
        cls._CACHE[key] = {
            'total_area': total_area,
            'cdf': cdf,
            'max_time': points[-1][0]
        }

    @classmethod
    def get_activity(cls, key: str, t_min: float, duration_override: float = None) -> float:
        points = cls._DATA.get(key)
        if not points: return 0.0
        
        # NOTE: duration_override is largely ignored to strictly respect the Clinical Curve provided.
        # But if the user sets DIA very short (e.g. 3h) and the curve goes to 5h, 
        # we probably should respect the curve shape but compress it? 
        # Or just respect the Curve because it IS the truth?
        # Given the explicit data, we trust the Curve's timeline (5h max).
        
        if t_min < 0: return 0.0
        if t_min > points[-1][0]: return 0.0
        
        # Linear Interpolation
        for i in range(1, len(points)):
            t1, y1 = points[i]
            if t_min <= t1:
                t0, y0 = points[i-1]
                # Interp
                ratio = (t_min - t0) / (t1 - t0)
                val = y0 + ratio * (y1 - y0)
                
                # Normalize? The function returns Activity Fraction.
                # Usually standard math curves return "Activity normalized to area=1".
                # The raw data is % of Max GIR.
                # We need to normalize by Total Area to keep units consistent (Total Insulin = 1 U).
                cls._ensure_cache(key)
                cache = cls._CACHE[key]
                if cache['total_area'] > 0:
                    return val / cache['total_area']
                return 0.0
                
        return 0.0

    @classmethod
    def get_iob(cls, key: str, t_min: float, duration_override: float = None) -> float:
        cls._ensure_cache(key)
        cache = cls._CACHE.get(key)
        if not cache: return 0.0
        
        if t_min <= 0: return 1.0
        if t_min >= cache['max_time']: return 0.0
        
        # Find Cumulative Area up to t_min
        cdf = cache['cdf']
        metrics_area = 0.0
        
        # Binary search or scan
        for i in range(1, len(cdf)):
            t1_cdf, area1 = cdf[i]
            if t_min <= t1_cdf:
                t0_cdf, area0 = cdf[i-1]
                
                # We need to interpolate area within the segment
                # Segment Area calculation again
                # Find y at t_min
                # (We could optimize by storing y in cdf, but let's re-get form _DATA or just lerp here)
                # Let's get raw Ys
                raw_pts = cls._DATA[key]
                t_start, y_start = raw_pts[i-1]
                t_end, y_end = raw_pts[i]
                
                # Fraction through segment
                ratio = (t_min - t_start) / (t_end - t_start)
                y_at_t = y_start + ratio * (y_end - y_start)
                
                # Area of this partial trapezoid
                dt = t_min - t_start
                local_area = dt * (y_start + y_at_t) / 2.0
                
                metrics_area = area0 + local_area
                break
        
        # IOB = 1 - (Consumed / Total)
        fraction_consumed = metrics_area / cache['total_area']
        return max(0.0, 1.0 - fraction_consumed)


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
