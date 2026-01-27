
import math

class InterpolatedCurves:
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
    
    _CACHE = {} 

    @classmethod
    def _ensure_cache(cls, key: str):
        if key in cls._CACHE: return
        points = cls._DATA.get(key)
        if not points: return 
        
        total_area = 0.0
        cdf = [(0, 0.0)] 
        
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
        
        cdf = cache['cdf']
        metrics_area = 0.0
        
        for i in range(1, len(cdf)):
            t1_cdf, area1 = cdf[i]
            if t_min <= t1_cdf:
                t0_cdf, area0 = cdf[i-1]
                
                # Interpolate area
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

def simulate():
    t_elapsed = 197 # 3h 17m
    
    dias_to_test = [3, 4, 5, 5.5, 6]
    models = ['fiasp', 'novorapid']
    
    print(f"--- Simulating Elapsed Time: {t_elapsed} min ---")
    
    for dia in dias_to_test:
        dia_min = dia * 60
        print(f"\nDIA: {dia}h ({dia_min} min)")
        for m in models:
            iob = InterpolatedCurves.get_iob(m, t_elapsed, dia_min)
            print(f"  {m}: {iob*100:.2f}% remaining")
            
            # Assuming a 5U bolus
            remaining_u = 5.0 * iob
            print(f"    -> If bolus was 5U: {remaining_u:.2f} U")

    print("\n--- Checking potential Timezone Errors ---")
    # What if the system thinks elapsed is (197 + 60) min? or (197 - 60)?
    offsets = [-60, 0, 60]
    dia_target = 5.5 * 60
    for off in offsets:
        t_eff = t_elapsed + off
        print(f"Offset {off} min => Effective Elapsed: {t_eff} min")
        iob = InterpolatedCurves.get_iob('novorapid', t_eff, dia_target)
        print(f"  Novorapid (5.5h): {iob*100:.2f}%")

if __name__ == "__main__":
    simulate()
