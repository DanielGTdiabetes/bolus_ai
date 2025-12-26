
import math

class InsulinCurves:
    @staticmethod
    def _walsh_tau(peak_min, duration_min):
        denom = 1 - 2 * peak_min / duration_min
        if denom == 0: return 0
        return peak_min * (1 - peak_min / duration_min) / denom

    @staticmethod
    def _walsh_F(t, duration, tau):
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

output = []
output.append("--- Testing Fiasp (Peak 55) ---")
for dia in [3, 4, 5]:
    duration = dia * 60
    iob = InsulinCurves.exponential_iob(43, 55, duration)
    remaining_of_4 = 4.0 * iob
    output.append(f"DIA {dia}h, Peak 55m, t=43m -> IOB%: {iob:.4f}, Rem of 4U: {remaining_of_4:.4f}U")

output.append("\n--- Testing NovoRapid (Peak 75) ---")
for dia in [4, 5]:
    duration = dia * 60
    iob = InsulinCurves.exponential_iob(43, 75, duration)
    remaining_of_4 = 4.0 * iob
    output.append(f"DIA {dia}h, Peak 75m, t=43m -> IOB%: {iob:.4f}, Rem of 4U: {remaining_of_4:.4f}U")

with open("iob_test_results.txt", "w") as f:
    f.write("\n".join(output))
