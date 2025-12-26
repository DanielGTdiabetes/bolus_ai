
from app.services.math.curves import InsulinCurves, InterpolatedCurves

print("--- Testing EMA Data-Driven Fiasp ---")
t_values = [15, 30, 45, 60, 105, 120]
for t in t_values:
    iob = InsulinCurves.get_iob(t, 300, 55, 'fiasp')
    rem4 = 4.0 * iob
    print(f"Time {t}min -> IOB%: {iob*100:.1f}%, Rem of 4U: {rem4:.2f}U")

print("\n--- Testing EMA Data-Driven NovoRapid ---")
for t in t_values:
    iob = InsulinCurves.get_iob(t, 300, 75, 'novorapid')
    rem4 = 4.0 * iob
    print(f"Time {t}min -> IOB%: {iob*100:.1f}%, Rem of 4U: {rem4:.2f}U")
