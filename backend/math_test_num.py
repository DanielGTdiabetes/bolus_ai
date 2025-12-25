import math

def exponential_activity(t_min, peak_min, duration_min):
    if t_min <= 0 or t_min >= duration_min: return 0.0
    tau = peak_min * (1 - peak_min / duration_min) / (1 - 2 * peak_min / duration_min)
    a = 2 * tau / duration_min
    S = 1 / (1 - a + (1 + a) * math.exp(-duration_min / tau))
    activity = (S / tau) * (1 - t_min / duration_min) * math.exp(-t_min / tau)
    return max(0.0, activity)

def verify_numerical():
    peak = 75.0
    duration = 300.0
    
    dt = 0.1
    total_area = 0.0
    t = 0
    while t <= duration:
        y = exponential_activity(t, peak, duration)
        total_area += y * dt
        t += dt
        
    print(f"Numerical Area: {total_area:.4f}")

if __name__ == "__main__":
    verify_numerical()
