
import math

class InterpolatedCurves:
    """
    Data-driven curves based on EMA/EPAR clinical studies (GIR).
    Source: User provided (Fiasp: 445421/2016, NovoRapid: 3211/2005)
    Values are % of Max GIR.
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
        if not points: return 
        
        # Calculate Total Area and CDF (Cumulative Area) using Trapezoidal Rule
        total_area = 0.0
        cdf = [(0, 0.0)] # (time, cumulative_area)
        
        for i in range(1, len(points)):
            t0, y0 = points[i-1]
            t1, y1 = points[i]
            
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
        
        if t_min < 0: return 0.0
        if t_min > points[-1][0]: return 0.0
        
        # Linear Interpolation
        for i in range(1, len(points)):
            t1, y1 = points[i]
            if t_min <= t1:
                t0, y0 = points[i-1]
                ratio = (t_min - t0) / (t1 - t0)
                val = y0 + ratio * (y1 - y0)
                
                # Normalize by Total Area to keep units consistent (Total Insulin = 1 U)
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
        
        for i in range(1, len(cdf)):
            t1_cdf, area1 = cdf[i]
            if t_min <= t1_cdf:
                t0_cdf, area0 = cdf[i-1]
                
                # Interpolate area within the segment
                raw_pts = cls._DATA[key]
                t_start, y_start = raw_pts[i-1]
                t_end, y_end = raw_pts[i]
                
                ratio = (t_min - t_start) / (t_end - t_start)
                y_at_t = y_start + ratio * (y_end - y_start)
                
                dt = t_min - t_start
                local_area = dt * (y_start + y_at_t) / 2.0
                
                metrics_area = area0 + local_area
                break
        
        fraction_consumed = metrics_area / cache['total_area']
        return max(0.0, 1.0 - fraction_consumed)


class InsulinCurves:
    """
    Standard insulin activity models + Proxy to InterpolatedCurves.
    """
    
    @staticmethod
    def _walsh_tau(peak_min, duration_min):
        if duration_min <= 0: return 0
        denom = 1 - 2 * peak_min / duration_min
        if denom == 0: return 0
        return peak_min * (1 - peak_min / duration_min) / denom

    @staticmethod
    def _walsh_F(t, duration, tau):
        if tau == 0: return 0
        term = (tau/duration) - 1 + (t/duration)
        return tau * math.exp(-t/tau) * term

    @staticmethod
    def exponential_activity(t_min: float, peak_min: float, duration_min: float) -> float:
        if t_min <= 0 or t_min >= duration_min: return 0.0
        tau = InsulinCurves._walsh_tau(peak_min, duration_min)
        if tau <= 0: return InsulinCurves.bilinear_activity(t_min, peak_min, duration_min)
        F0 = InsulinCurves._walsh_F(0, duration_min, tau)
        FD = InsulinCurves._walsh_F(duration_min, duration_min, tau)
        area = FD - F0
        if area == 0: return 0.0
        raw = (1 - t_min / duration_min) * math.exp(-t_min / tau)
        return raw / area

    @staticmethod
    def bilinear_activity(t_min: float, peak_min: float, duration_min: float) -> float:
        if t_min <= 0 or t_min >= duration_min: return 0.0
        h = 2.0 / duration_min
        if t_min < peak_min:
            return h * (t_min / peak_min)
        else:
            return h * ((duration_min - t_min) / (duration_min - peak_min))

    @staticmethod
    def exponential_iob(t_min: float, peak_min: float, duration_min: float) -> float:
        if t_min <= 0: return 1.0
        if t_min >= duration_min: return 0.0
        tau = InsulinCurves._walsh_tau(peak_min, duration_min)
        if tau <= 0: return max(0.0, 1.0 - t_min / duration_min)
        F0 = InsulinCurves._walsh_F(0, duration_min, tau)
        FD = InsulinCurves._walsh_F(duration_min, duration_min, tau)
        Ft = InsulinCurves._walsh_F(t_min, duration_min, tau)
        denom = FD - F0
        if denom == 0: return 0.0
        return (FD - Ft) / denom

    @staticmethod
    def bilinear_iob(t_min: float, peak_min: float, duration_min: float) -> float:
        if t_min <= 0: return 1.0
        if t_min >= duration_min: return 0.0
        # Calculate analytically
        h = 2.0 / duration_min
        consumed = 0.0
        if t_min < peak_min:
             current_h = h * (t_min / peak_min)
             consumed = 0.5 * t_min * current_h
        else:
             area1 = 0.5 * peak_min * h
             rem_base = duration_min - t_min
             rem_height = h * (rem_base / (duration_min - peak_min))
             rem_area = 0.5 * rem_base * rem_height
             consumed = 1.0 - rem_area
        return max(0.0, 1.0 - consumed)

    @staticmethod
    def get_iob(t_min: float, duration_min: float, peak_min: float, model_type: str) -> float:
        m = model_type.lower()
        if m == 'fiasp':
            return InterpolatedCurves.get_iob('fiasp', t_min, duration_min)
        elif m == 'novorapid':
            return InterpolatedCurves.get_iob('novorapid', t_min, duration_min)
        
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


class CarbCurves:
    @staticmethod
    def linear_absorption(t_min: float, duration_min: float) -> float:
        if t_min <= 0 or t_min >= duration_min: return 0.0
        return 1.0 / duration_min

    @staticmethod
    def variable_absorption(t_min: float, duration_min: float, peak_min: float = 60) -> float:
        if t_min <= 0 or t_min >= duration_min: return 0.0
        h = 2.0 / duration_min
        if t_min < peak_min:
             return h * (t_min / peak_min)
        else:
             return h * ((duration_min - t_min) / (duration_min - peak_min))
