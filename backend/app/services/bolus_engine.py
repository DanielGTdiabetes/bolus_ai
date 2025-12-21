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
    
    val60 = points[60]
    val120 = points[120]
    
    if minutes <= 60:
        pct = minutes / 60.0
        return val60 * pct
    elif minutes <= 120:
        pct = (minutes - 60) / 60.0
        return val60 + (val120 - val60) * pct
    else:
        return val120



def _smart_round(
    value: float,
    step: float,
    trend: str,
    max_change: float,
    explain: list[str]
) -> float:
    """
    Techne Rounding:
    - Rising (DoubleUp, SingleUp, FortyFiveUp) -> Ceil to step
    - Falling (DoubleDown, SingleDown, FortyFiveDown) -> Floor to step
    - Flat/None -> Nearest (Standard)
    
    Subject to max_change safety limit.
    """
    standard = round(value / step) * step
    
    # Map Trend
    t = trend.lower()
    mode = "neutral"
    if t in ["doubleup", "singleup", "fortyfiveup"]:
        mode = "up"
    elif t in ["doubledown", "singledown", "fortyfivedown"]:
        mode = "down"
        
    if mode == "neutral":
        return standard
        
    proposed = standard
    if mode == "up":
        proposed = math.ceil(value / step) * step
    else:
        proposed = math.floor(value / step) * step
        
    # Safety Check
    if abs(proposed - value) > max_change + 0.001:
        explain.append(f"   (Techne) Flecha {trend}: Propuesto {proposed:.2f} desvía > {max_change}U. Usando estándar.")
        return standard

    if abs(proposed - standard) > 0.001:
         explain.append(f"   (Techne) Flecha {trend} ({mode.upper()}): {value:.2f} -> {proposed:.2f} U")
         return proposed
         
    return standard


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
        dia_hours=settings.iob.dia_hours,
        max_bolus_final=settings.max_bolus_u
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
    
    # NEW VALIDATION LOGIC -----------------------------------------
    bg_usable = False
    
    if bg is not None:
         if glucose_info.is_stale:
             warnings.append(f"Glucosa ({bg}) 'stale' (>10min antigua). NO se corrige.")
             explain.append(f"B) Corrección: DATOS ANTIGUOS ({glucose_info.age_minutes:.0f} min). Ignorados.")
         else:
             bg_usable = True
    
    if bg_usable:
        if bg > target:
            diff = bg - target
            corr_u = diff / isf
            # Cap de corrección
            if corr_u > settings.max_correction_u:
                explain.append(f"   Corrección calculada {corr_u:.2f} U supera límite {settings.max_correction_u} U")
                corr_u = settings.max_correction_u
            
            trend_str = f" ({glucose_info.trend})" if glucose_info.trend else ""
            age_str = f" [{glucose_info.age_minutes:.0f}m]" if glucose_info.age_minutes is not None else ""
            explain.append(f"B) Corrección: ({bg:.0f}{trend_str}{age_str} - {target:.0f}) / {isf:.0f}(ISF) = {corr_u:.2f} U")
        elif bg < 70:
            warnings.append(f"Glucosa baja ({bg}), se recomienda NO poner bolo o tratar hipo.")
            explain.append(f"B) Corrección: Glucosa < 70 ({bg}), riesgo hipoglucemia.")
        else:
             explain.append(f"B) Corrección: Glucosa ({bg}) <= Objetivo ({target}). 0 U")
    else:
        if bg is None:
            explain.append("B) Corrección: 0 U (Falta glucosa)")
            if settings.nightscout.enabled and not glucose_info.source == "nightscout":
                 warnings.append("Nightscout configurado pero no respondió.")
        # If stale, we already appended rationale above.

    # 4. IOB
    total_base = meal_u + corr_u
    
    if request.ignore_iob_for_meal:
        # "Wizard" Logic: IOB only offsets correction, never meal.
        remaining_iob = max(0.0, iob_u)
        corr_after_iob = max(0.0, corr_u - remaining_iob)
        total_after_iob = meal_u + corr_after_iob
        
        if iob_u > 0:
            explain.append(f"C) IOB (Postre): {iob_u:.2f} U activos.")
            if corr_u > 0:
                explain.append(f"   Resta solo de corrección: {corr_u:.2f} -> {corr_after_iob:.2f} U")
            else:
                explain.append("   Ignorado para comida (Estrategia Postre/Segundo Plato).")
            
            explain.append(f"   Neto = {meal_u:.2f} (Comida) + {corr_after_iob:.2f} (Corr. Ajustada) = {total_after_iob:.2f} U")
            explain.append("   ⚠️ Consejo: Si tu bolo anterior fue hace < 2h, considera esperar 15-20 min antes de inyectar este bolo (Retraso por Vaciado Gástrico).")
        else:
            explain.append("C) IOB: 0 U")
            
    else:
        # Standard "Loop" Logic: IOB offsets everything.
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
    # Techne Validation
    techne_trend = glucose_info.trend
    techne_ok = False
    if settings.techne.enabled and techne_trend:
        # Conditions: Glucosa >= Target, IOB low, No exercise
        cond_bg = (glucose_info.mgdl is not None and glucose_info.mgdl >= target)
        cond_iob = (iob_u <= settings.techne.safety_iob_threshold)
        cond_ex = (request.exercise.minutes == 0)
        
        if cond_bg and cond_iob and cond_ex:
            techne_ok = True
        elif settings.techne.enabled:
            # Optional debug logs for why it was skipped?
            pass

    # 6. Bolo Extendido (Slow Meal)
    kind = "normal"
    upfront = total_after_exercise
    later = 0.0
    duration = 0
    step = settings.round_step_u

    if request.slow_meal.enabled:
        pct = request.slow_meal.upfront_pct
        upfront_raw = total_after_exercise * pct
        later_raw = total_after_exercise - upfront_raw
        
        # Apply Techne to Upfront Only
        if techne_ok:
            upfront = _smart_round(upfront_raw, step, techne_trend, settings.techne.max_step_change, explain)
        else:
            upfront = _round_step(upfront_raw, step)
            
        later = _round_step(later_raw, step)
        
        if later < step:
             explain.append("E) Bolo extendido: la parte extendida es despreciable (< step). Cambiando a Normal.")
             kind = "normal"
             # Re-calc upfront based on total (with Techne if applicable)
             if techne_ok:
                 upfront = _smart_round(total_after_exercise, step, techne_trend, settings.techne.max_step_change, explain)
             else:
                 upfront = _round_step(total_after_exercise, step)
             later = 0.0
        else:
             kind = "extended"
             duration = request.slow_meal.duration_min
             explain.append(f"E) Estrategia Dual/Cuadrada: Split {int(pct*100)}% / {int(100 - pct*100)}%")
             explain.append(f"   Ahora: {upfront:.2f} U, Luego: {later:.2f} U en {duration} min")

    else:
         if techne_ok:
             upfront = _smart_round(total_after_exercise, step, techne_trend, settings.techne.max_step_change, explain)
         else:
             upfront = _round_step(total_after_exercise, step)

    # 7. Límites finales
    total_final = upfront + later
    if total_final > settings.max_bolus_u:
        warnings.append(f"Bolo total supera máximo de usuario ({settings.max_bolus_u} U). Limitado.")
        ratio = settings.max_bolus_u / total_final
        upfront = _round_step(upfront * ratio, settings.round_step_u)
        later = _round_step(later * ratio, settings.round_step_u)
        total_final = upfront + later 
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

    return BolusResponseV2(
        total_u=round(total_final, 2),
        kind=kind,
        upfront_u=round(upfront, 2),
        later_u=round(later, 2),
        duration_min=duration,
        iob_u=round(iob_u, 2),
        meal_bolus_u=round(meal_u, 2),
        correction_u=round(corr_u, 2),
        total_u_raw=round(total_base, 2),
        total_u_final=round(total_final, 2),
        glucose=glucose_info,
        used_params=used_params,
        suggestions=suggestions,
        explain=explain,
        warnings=warnings
    )
