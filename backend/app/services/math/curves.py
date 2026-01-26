
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
        
        # Scale logic: Stretch/Compress curve to fit duration_override
        original_max = points[-1][0]
        scale_factor = 1.0
        
        if duration_override and duration_override > 0 and abs(duration_override - original_max) > 1.0:
            scale_factor = duration_override / original_max
            # Transform user time (e.g. 330m) to curve time (e.g. 300m)
            t_min = t_min / scale_factor
        
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
                    base_val = val / cache['total_area']
                    # Amplitude must be inversely scaled to preserve Area=1 (Wider curve = Lower peak)
                    return base_val / scale_factor
                return 0.0
                
        return 0.0

    @classmethod
    def get_iob(cls, key: str, t_min: float, duration_override: float = None) -> float:
        cls._ensure_cache(key)
        cache = cls._CACHE.get(key)
        if not cache: return 0.0
        
        # Scale logic for IOB
        if duration_override and duration_override > 0 and abs(duration_override - cache['max_time']) > 1.0:
            scale_factor = duration_override / cache['max_time']
            t_min = t_min / scale_factor
        
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

    @staticmethod
    def hovorka_shape(t: float, t_max: float) -> float:
        """
        Returns normalized rate at time t for a curve peaking at t_max.
        Shape: t * exp(-t/t_max) scaled to be unit area? 
        The standard density function is (t / t_max^2) * exp(-t/t_max).
        Total area = 1.
        """
        if t <= 0 or t_max <= 0: return 0.0
        return (t / (t_max * t_max)) * math.exp(-t / t_max)

    @staticmethod
    def biexponential_absorption(t_min: float, params: dict) -> float:
        """
        params: {
            'f': float,        # Fraction fast (0.0 - 1.0)
            't_max_r': float,  # Time to peak for fast component (min)
            't_max_l': float   # Time to peak for slow component (min)
        }
        """
        f = params.get('f', 0.5)
        tr = params.get('t_max_r', 45.0)
        tl = params.get('t_max_l', 120.0)
        
        # Fast component
        rate_r = CarbCurves.hovorka_shape(t_min, tr)
        
        # Slow component
        rate_l = CarbCurves.hovorka_shape(t_min, tl)
        
        return (f * rate_r) + ((1 - f) * rate_l)

    @staticmethod
    def get_biexponential_params(carbs_g: float, fiber_g: float = 0, fat_g: float = 0, protein_g: float = 0) -> dict:
        """
        Heuristic to determine absorption parameters based on composition.
        """
        # Base values (Default to "Medium GI")
        f = 0.7 
        t_max_r = 40.0
        t_max_l = 90.0
        
        if carbs_g <= 0:
            return {'f': 0.5, 't_max_r': 40, 't_max_l': 90}

        # 1. Fiber Impact (Strong delay)
        # IGNORE if fiber is negligible (< 5g) based on user rule
        fiber_ratio = 0.0
        if fiber_g >= 5.0 and carbs_g > 0:
             fiber_ratio = fiber_g / carbs_g
        
        # Decrease fast fraction as fiber increases
        # If ratio is 0.0 -> f=0.8 (Upper bound for pure sugar/starch)
        # If ratio is 0.5 -> f=0.3
        # Linear slope
        f_fiber_adj = max(0.0, fiber_ratio * 1.0) 
        f -= f_fiber_adj

        # 2. Fat/Protein Impact (Pizza Effect)
        # 1g Fat ~ delays like 2g carbs? Heuristic:
        # High fat extends the TAIL (t_max_l) and reduces f
        fp_units = fat_g + (protein_g * 0.5)
        if fp_units > 10:
             # Reduce fast fraction
             f -= (fp_units / 100.0)
             # Extend slow curve peak
             t_max_l += (fp_units * 1.5)

        # Clamping
        f = max(0.2, min(0.9, f))
        t_max_l = max(60.0, min(240.0, t_max_l))
        
        return {
            'f': f,
            't_min_r': 0, # Placeholder if needed
            't_max_r': t_max_r,
            't_max_l': t_max_l
        }

    @staticmethod
    def get_profile_params(profile_name: str) -> dict:
        """
        Preset profiles based on user requirements:
        - Fast: Peak 20-30 min, Duration ~1.5h
        - Med: Peak 45-60 min, Duration ~3h
        - Slow: Peak 90-120 min, Duration ~4-5h
        These use the biexponential model for smooth tails.
        """
        p = profile_name.lower()
        if p == "fast":
            return {'f': 0.9, 't_max_r': 25.0, 't_max_l': 60.0}
        elif p == "slow":
            return {'f': 0.3, 't_max_r': 40.0, 't_max_l': 120.0}
        else: # "med" or default
            return {'f': 0.7, 't_max_r': 45.0, 't_max_l': 90.0}

    @staticmethod
    def get_dynamic_carb_params(carbs_g: float, fat_g: float, profile_pref: str = "med") -> dict:
        """
        Dynamically calculates biexponential parameters based on fat content.
        - Fat shifts the fast peak (t_max_r) and slow peak (t_max_l) to the right.
        - Fat decreases the fast fraction (f).
        """
        # Base values from preference
        base = CarbCurves.get_profile_params(profile_pref)
        f = base['f']
        t_max_r = base['t_max_r']
        t_max_l = base['t_max_l']

        # Modulate by Fat (capped at 50g for stability)
        fat_eff = min(fat_g, 50.0)
        
        # 1. Shift peaks (Grasa desplaza el pico)
        # Suavizado: 0.4 min/g para rápido, 0.6 min/g para lento
        t_max_r += (0.4 * fat_eff)
        t_max_l += (0.6 * fat_eff)

        # 2. Decrease fast fraction
        # Suavizado: -0.003 por gramo, con suelo relativo
        f = max(base['f'] * 0.6, f - (0.003 * fat_eff))

        return {
            'f': f,
            't_max_r': t_max_r,
            't_max_l': t_max_l
        }
