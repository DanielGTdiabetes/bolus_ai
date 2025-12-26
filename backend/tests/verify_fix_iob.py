
from app.services.math.curves import InsulinCurves

print("--- Testing NEW Fiasp (Bilinear Peak 55) ---")
for dia in [3, 4, 5]:
    duration = dia * 60
    # User Case: 43 mins after 4U
    iob = InsulinCurves.get_iob(43, duration, 55, 'fiasp')
    remaining_of_4 = 4.0 * iob
    print(f"DIA {dia}h, Peak 55m, t=43m -> IOB%: {iob:.2f}, Rem of 4U: {remaining_of_4:.2f}U")

print("\n--- Testing NEW NovoRapid (Bilinear Peak 75) ---")
for dia in [4, 5]:
    duration = dia * 60
    iob = InsulinCurves.get_iob(43, duration, 75, 'novorapid')
    remaining_of_4 = 4.0 * iob
    print(f"DIA {dia}h, Peak 75m, t=43m -> IOB%: {iob:.2f}, Rem of 4U: {remaining_of_4:.2f}U")
