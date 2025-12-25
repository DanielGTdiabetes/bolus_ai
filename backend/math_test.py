import math

def verify_math():
    peak = 75.0
    duration = 300.0
    
    tau = peak * (1 - peak / duration) / (1 - 2 * peak / duration)
    a = 2 * tau / duration
    S = 1 / (1 - a + (1 + a) * math.exp(-duration / tau))
    
    print(f"Debug: tau={tau:.2f}, S={S:.4f}")
    
    def get_F(t):
        term = (tau/duration) - 1 + (t/duration)
        return (S/tau) * tau * math.exp(-t/tau) * term

    F0 = get_F(0)
    F_end = get_F(duration)
    
    print(f"F(0)={F0:.4f}, F(end)={F_end:.4f}")
    
    total_area = F_end - F0
    print(f"Total Area (F_end - F0) = {total_area:.4f} (Should be 1.0 ideally)")
    
    for t in [0, 55, 75, 150, 299, 300]:
        F = get_F(t)
        cum = F - F0
        iob = 1.0 - cum
        print(f"T={t}: Active={cum:.4f}, IOB={iob:.4f}")

if __name__ == "__main__":
    verify_math()
