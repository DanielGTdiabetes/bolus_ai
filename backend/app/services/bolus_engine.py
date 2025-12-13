import math
from typing import Optional

from app.models.bolus_v2 import (
    BolusRequestV2,
    BolusResponseV2,
    BolusSuggestions,
    GlucoseUsed,
    UsedParams,
)
from app.models.settings import UserSettings


def _round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(value / step) * step


def calculate_exercise_reduction(minutes: int, intensity: str) -> float:
    """
    Interpolate reduction based on minutes and intensity.
    Table:
    60min: low 0.15, mod 0.30, high 0.45
    120min: low 0.30, mod 0.55, high 0.75
    """
    if minutes <= 0:
        return 0.0

    # Define points
    table = {
        "low": {60: 0.15, 120: 0.30},
        "moderate": {60: 0.30, 120: 0.55},
        "high": {60: 0.45, 120: 0.75},
    }
    
    intens = intensity.lower()
    if intens not in table:
        intens = "moderate"
    
    points = table[intens]
    
    # Cap inputs for simplicity (or clamp logic)
    # If < 60, linear from 0 at 0 min? Or use 60 val as base if > 30?
    # Let's simple linear from 0 to 120+
    # 0 min -> 0.0
    # 60 min -> val60
    # 120 min -> val120
    
    val60 = points[60]
    val120 = points[120]
    
    if minutes <= 60:
        # Interpolate 0 -> 60
        pct = minutes / 60.0
        return val60 * pct
    elif minutes <= 120:
        # Interpolate 60 -> 120
        pct = (minutes - 60) / 60.0
        return val60 + (val120 - val60) * pct
    else:
        # > 120. Cap at 120 value? Or extrapolate slightly? 
        # Clamp at 120 val max? Or max 0.9.
        # Let's cap at val120 to be safe.
        return val120


def calculate_bolus_v2(
    request: BolusRequestV2,
    settings: UserSettings,
    iob_u: float,
    glucose_info: GlucoseUsed,
) -> BolusResponseV2:
    explain = []
    warnings = []
    
    # 1. Resolver parámetros
    meal_slot = request.meal_slot
    cr = getattr(settings.cr, meal_slot, 10.0)
    isf = getattr(settings.cf, meal_slot, 30.0)
    target = request.target_mgdl or settings.targets.mid

    # Protección de división
    if cr <= 0.1:
        cr = 10.0
        warnings.append("CR inválido, usando 10.0 g/U")
    if isf <= 5:
        isf = 30.0
        warnings.append("ISF/CF inválido, usando 30.0 mg/dL/U")
        
    used_params = UsedParams(
        cr_g_per_u=cr,
        isf_mgdl_per_u=isf,
        target_mgdl=target,
        dia_hours=settings.iob.dia_hours
    )

    # 2. Comida
    meal_u = 0.0
    if request.carbs_g > 0:
        meal_u = request.carbs_g / cr
        explain.append(f"A) Comida: {request.carbs_g:.1f}g / {cr:.1f}(CR) = {meal_u:.2f} U")
    else:
        explain.append("A) Comida: 0g (sin bolo comida)")

    # 3. Corrección
    corr_u = 0.0
    bg = glucose_info.mgdl
    if bg is not None:
        if bg > target:
            diff = bg - target
            corr_u = diff / isf
            # Cap de corrección
            if corr_u > settings.max_correction_u:
                explain.append(f"   Corrección calculada {corr_u:.2f} U supera límite {settings.max_correction_u} U")
                corr_u = settings.max_correction_u
            
            explain.append(f"B) Corrección: ({bg:.0f} - {target:.0f}) / {isf:.0f}(ISF) = {corr_u:.2f} U")
        elif bg < 70:
            warnings.append(f"Glucosa baja ({bg}), se recomienda NO poner bolo o tratar hipo.")
            explain.append(f"B) Corrección: Glucosa < 70 ({bg}), riesgo hipoglucemia.")
        else:
             explain.append(f"B) Corrección: Glucosa ({bg}) <= Objetivo ({target}). 0 U")
    else:
        explain.append("B) Corrección: 0 U (Falta glucosa)")
        if settings.nightscout.enabled and not glucose_info.source == "nightscout":
             warnings.append("Nightscout configurado pero no respondió.")

    # 4. IOB
    total_base = meal_u + corr_u
    total_after_iob = max(0.0, total_base - iob_u)
    
    if iob_u > 0:
        explain.append(f"C) IOB: {iob_u:.2f} U activos.")
        explain.append(f"   Neto = ({meal_u:.2f} + {corr_u:.2f}) - {iob_u:.2f} = {total_after_iob:.2f} U")
    else:
        explain.append("C) IOB: 0 U")
    
    # 5. Ejercicio
    total_after_exercise = total_after_iob
    if request.exercise.planned and request.exercise.minutes > 0:
        reduction_factor = calculate_exercise_reduction(request.exercise.minutes, request.exercise.intensity)
        reduction_factor = min(reduction_factor, 0.9) # Max 90% reduction
        
        total_after_exercise = total_after_iob * (1.0 - reduction_factor)
        pct_show = int(reduction_factor * 100)
        explain.append(f"D) Ejercicio: {request.exercise.intensity} {request.exercise.minutes}min -> -{pct_show}%")
        explain.append(f"   Reducido: {total_after_iob:.2f} -> {total_after_exercise:.2f} U")

    # 6. Bolo Extendido (Slow Meal)
    kind = "normal"
    upfront = total_after_exercise
    later = 0.0
    duration = 0
    
    if request.slow_meal.enabled:
        # Split logic
        pct = request.slow_meal.upfront_pct
        upfront_raw = total_after_exercise * pct
        later_raw = total_after_exercise - upfront_raw
        
        # Round parts separately? User says "round_step(total_after_exercise * upfront_pct)"
        step = settings.round_step_u
        upfront = _round_step(upfront_raw, step)
        later = _round_step(later_raw, step)
        
        # Si later es muy pequeño, volver a normal
        if later < step:
             explain.append("E) Bolo extendido: la parte extendida es despreciable (< step). Cambiando a Normal.")
             kind = "normal"
             # Recalculate full upfront rounded
             upfront = _round_step(total_after_exercise, step)
             later = 0.0
        else:
             kind = "extended"
             duration = request.slow_meal.duration_min
             explain.append(f"E) Estrategia Dual/Cuadrada: Split {int(pct*100)}% / {int(100 - pct*100)}%")
             explain.append(f"   Ahora: {upfront:.2f} U, Luego: {later:.2f} U en {duration} min")

    else:
         # Normal rounding check
         step = settings.round_step_u
         upfront = _round_step(total_after_exercise, step)
         
         if upfront != total_after_exercise:
              # Just notation
              pass
    
    # 7. Límites finales
    total_final = upfront + later
    if total_final > settings.max_bolus_u:
        warnings.append(f"Bolo total supera máximo de usuario ({settings.max_bolus_u} U). Limitado.")
        # Scale down proportionally? Or just cap upfront?
        # Simpler: cap upfront first.
        ratio = settings.max_bolus_u / total_final
        upfront = _round_step(upfront * ratio, settings.round_step_u)
        later = _round_step(later * ratio, settings.round_step_u)
        total_final = upfront + later # Recalc
        explain.append(f"F) Límite de seguridad aplicado: Total ahora {total_final:.2f} U")

    # 8. Sugerencias TDD
    suggestions = BolusSuggestions()
    if settings.tdd_u and settings.tdd_u > 0:
        sug_icr = 500.0 / settings.tdd_u
        sug_isf = 1800.0 / settings.tdd_u
        suggestions = BolusSuggestions(
            icr_g_per_u=round(sug_icr, 1),
            isf_mgdl_per_u=round(sug_isf, 1)
        )
        if abs(sug_icr - cr) > 5 or abs(sug_isf - isf) > 20:
             # Add to explain if divergent? Optional.
             pass

    return BolusResponseV2(
        total_u=round(total_final, 2),
        kind=kind,
        upfront_u=round(upfront, 2),
        later_u=round(later, 2),
        duration_min=duration,
        iob_u=round(iob_u, 2),
        glucose=glucose_info,
        used_params=used_params,
        suggestions=suggestions,
        explain=explain,
        warnings=warnings
    )
