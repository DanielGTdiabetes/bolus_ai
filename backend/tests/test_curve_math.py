
import math

class InsulinCurves:
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
    def exponential_iob(t_min: float, peak_min: float, duration_min: float) -> float:
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

print("--- Fiasp (Peak 55, DIA 240) ---")
for t in [0, 30, 60, 90, 120, 180, 240]:
    iob = InsulinCurves.exponential_iob(t, 55, 240)
    print(f"T={t} min: IOB={iob*100:.1f}%")

print("\n--- Fiasp (Peak 55, DIA 180) ---")
for t in [0, 30, 60, 90, 120, 180]:
    iob = InsulinCurves.exponential_iob(t, 55, 180)
    print(f"T={t} min: IOB={iob*100:.1f}%")
