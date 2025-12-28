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
    autosens_ratio: float = 1.0,
    autosens_reason: Optional[str] = None
) -> BolusResponseV2:
    explain = []
    warnings = []
    
    # 1. Resolver parámetros Base
    meal_slot = request.meal_slot
    cr_base = getattr(settings.cr, meal_slot, 10.0)
    isf_base = getattr(settings.cf, meal_slot, 30.0)
    target = request.target_mgdl or settings.targets.mid

    # Autosens Application
    # Ratio > 1 means Resistance -> Needs more insulin -> Lower ISF, Lower CR
    # Ratio < 1 means Sensitivity -> Needs less insulin -> Higher ISF, Higher CR
    
    effective_ratio = autosens_ratio
    # Safety clamp explicitly here just in case (though service does it)
    if effective_ratio < 0.7: effective_ratio = 0.7
    if effective_ratio > 1.3: effective_ratio = 1.3
    
    isf = isf_base / effective_ratio
    cr = cr_base / effective_ratio
    
    if abs(effective_ratio - 1.0) > 0.01:
        explain.append(f"🔍 Autosens: Factor {effective_ratio:.2f} ({autosens_reason or 'Ajuste dinámico'})")
        explain.append(f"   ISF: {isf_base:.1f} -> {isf:.1f}")
        explain.append(f"   CR:  {cr_base:.1f} -> {cr:.1f}")
    
    # Protección de división
    if cr <= 0.1:
        cr = 10.0
        warnings.append("CR inválido, usando 10.0 g/U")
    if isf <= 5:
        isf = 30.0
        warnings.append("ISF/CF inválido, usando 30.0 mg/dL/U")
        
    used_params = UsedParams(
        cr_g_per_u=round(cr, 1),
        isf_mgdl_per_u=round(isf, 1),
        target_mgdl=target,
        dia_hours=settings.iob.dia_hours,
        insulin_model=settings.iob.curve,
        max_bolus_final=settings.max_bolus_u,
        isf_base=isf_base,
        autosens_ratio=effective_ratio,
        autosens_reason=autosens_reason
    )
    
    # Global Warnings
    if request.alcohol:
        warnings.append("Alcohol Activo: Riesgo de hipoglucemia tardía. Monitorea tu glucosa.")

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

        # Always calculate correction, even if negative (to reduce meal bolus if needed)
        diff = bg - target
        corr_u = diff / isf
        
        # Cap de corrección positiva
        if corr_u > settings.max_correction_u:
            explain.append(f"   Corrección calculada {corr_u:.2f} U supera límite {settings.max_correction_u} U")
            corr_u = settings.max_correction_u
        
        trend_str = f" ({glucose_info.trend})" if glucose_info.trend else ""
        age_str = f" [{glucose_info.age_minutes:.0f}m]" if glucose_info.age_minutes is not None else ""
        
        explain.append(f"B) Corrección: ({bg:.0f}{trend_str}{age_str} - {target:.0f}) / {isf:.0f}(ISF) = {corr_u:.2f} U")

        if bg < 70:
            warnings.append(f"Glucosa baja ({bg}). La corrección negativa reducirá el bolo de comida.")
    else:
        if bg is None:
            explain.append("B) Corrección: 0 U (Falta glucosa)")
            if settings.nightscout.enabled and not glucose_info.source == "nightscout":
                 warnings.append("Nightscout configurado pero no respondió.")
        # If stale, we already appended rationale above.

    # 4. IOB
    total_base = meal_u + corr_u
    
    if request.ignore_iob:
        # --- ESTRATEGIA REACTIVA / MICRO-BOLOS (Grasas/Postre) ---
        explain.append("--- MODO REACTIVO (GRASAS/POSTRE) ---")
        
        # --- ESTRATEGIA REACTIVA / MICRO-BOLOS (Grasas/Postre) ---
        explain.append("--- MODO REACTIVO (GRASAS/POSTRE) ---")
        
        # 1. Safety Gates (Time & Alcohol)
        micro_bolus_u = 0.0
        safety_ok = True
        
        # A) Time Gate (Avoid Stacking on Peak)
        # If last bolus was < 75 min ago, we are likely near peak. Dangerous to add more blind corrections.
        last_min = request.last_bolus_minutes
        if last_min is not None and last_min < 75:
             explain.append(f"⛔ SEGURIDAD TIEMPO: Último bolo hace {last_min} min (<75 min).")
             explain.append("   Riesgo de stacking en pico. Se deniega micro-bolo.")
             warnings.append(f"Espera: Bolo reciente ({last_min} min).")
             safety_ok = False
        
        if safety_ok:
            explain.append(f"1. IOB Ignorado para cálculo base: {iob_u:.2f} U (Bolo previo > 75 min)")
            
            # Analizar Tendencia
            is_rising = False
            trend_arrow = glucose_info.trend or ""
            if trend_arrow.upper() in ["DOUBLEUP", "SINGLEUP", "FORTYFIVEUP"]:
                is_rising = True
                explain.append(f"2. Tendencia: Subiendo ({trend_arrow}) ↗️.")
            elif trend_arrow.upper() in ["FLAT"]:
                explain.append(f"2. Tendencia: Estable ({trend_arrow}) ➡️.")
            else:
                 explain.append(f"2. Tendencia: {trend_arrow}.")

            # B) Alcohol Soft Landing
            # If alcohol is present, we don't BLOCK, but we DAMPEN significantly.
            reduction_factor = 1.0
            if request.alcohol:
                reduction_factor = 0.5
                explain.append("🍷 ALCOHOL ACTIVO: Corrección reducida al 50% por seguridad.")
                warnings.append("Modo Alcohol: Dosis reducida 50%.")

            # 2. Calcular Corrección
            raw_correction = 0.0
            if bg_usable and bg > target:
                raw_correction = (bg - target) / isf
            
            # 3. Reglas de Micro-Bolos (Safety Caps)
            base_limit = 1.0
            pct = 0.5 * reduction_factor # Inherit alcohol reduction
            
            if is_rising:
                base_limit = 1.5
                pct = 0.7 * reduction_factor
            
            # IOB Check (Secondary Safety)
            # If IOB is HUGE (> 3.5), we block regardless of time (maybe extended bolus overlap?)
            if iob_u > 3.5:
                 explain.append(f"⚠️ IOB muy alto ({iob_u:.1f}U). Cancelando micro-bolo por precaución.")
                 micro_bolus_u = 0.0
            else:
                # Normal Calculation
                # Umbral de Disparo (>130 mg/dL para actuar, salvo que suba mucho)
                if bg < 130 and not is_rising:
                     explain.append("   Glucosa < 130 y estable. Esperar.")
                     micro_bolus_u = 0.0
                else:
                     calc_dose = raw_correction * pct
                     # Min floor for very small corrections if not alcohol (alcohol always strictly proportional)
                     if not request.alcohol and raw_correction < 0.8: 
                         calc_dose = raw_correction
                     
                     
                     if calc_dose > base_limit:
                         calc_dose = base_limit
                         explain.append(f"   (Limitado a {base_limit} U)")
                     
                     # 4. Round to User Step (Critical for Pen Users)
                     # Before this, we had precise theoretical values (e.g 0.8), but pens are 0.5 or 1.0 steps.
                     # We must round down or up safely.
                     step = settings.round_step_u
                     calc_dose = _round_step(calc_dose, step)
                     
                     if calc_dose < step:
                          # If result is smaller than minimum deliverable, show 0 BUT explain
                          if calc_dose > 0.001: 
                               explain.append(f"   Dosis {calc_dose:.2f}U < paso mínimo {step}U. Se redondea a 0.")
                          calc_dose = 0.0
                         
                     micro_bolus_u = calc_dose
            
            if micro_bolus_u > 0:
                explain.append(f"3. Micro-Bolo final: {micro_bolus_u:.2f} U")
            else:
                if safety_ok and micro_bolus_u == 0:
                   explain.append("3. Micro-Bolo: 0.00 U")

        # Asignación final
        # EN MODO REACTIVO/POSTRE (Ignore IOB), NO descontamos IOB de la comida.
        # El usuario asume que quiere cubrir este 'Postre' completo.
        meal_net = meal_u 
        explain.append(f"   (Modo Postre: IOB no descuenta comida. {meal_u:.2f} U íntegras)") 
        total_after_iob = meal_net + micro_bolus_u

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
        # --- LOGIC A: Manual Dual Bolus (User input) ---
        pct = request.slow_meal.upfront_pct
        upfront_raw = total_after_exercise * pct
        later_raw = total_after_exercise - upfront_raw
    elif request.fat_g > 0 or request.protein_g > 0:
        # --- LOGIC B: Warsaw Method (Auto-Dual from Mactros) ---
        # Formula:
        # F_kcal = fat * 9
        # P_kcal = protein * 4
        # Total_kcal = F_kcal + P_kcal
        # FPU (Fat-Protein Units) = Total_kcal / 10 (approx equivalent carbs)
        
        fat_kcal = request.fat_g * 9.0
        prot_kcal = request.protein_g * 4.0
        total_extra_kcal = fat_kcal + prot_kcal
        
        warsaw_u = 0.0
        
        # Calculate Warsaw Insulin if enabled, regardless of threshold (to decide where to put it)
        if settings.warsaw.enabled:
             fpu_equivalent_carbs = total_extra_kcal / 10.0
             safety_factor = settings.warsaw.safety_factor 
             warsaw_u = (fpu_equivalent_carbs * safety_factor) / cr
             
        # Threshold Logic:
        # If > Threshold -> EXTEND (Dual Bolus)
        # If <= Threshold -> UPFRONT (Simple Bolus, but included)
        
        if settings.warsaw.enabled and total_extra_kcal >= settings.warsaw.trigger_threshold_kcal:
             
             # Duration Calculation (Warsaw)
             if fpu_equivalent_carbs < 20: duration_calc = 180 # 3h
             elif fpu_equivalent_carbs < 40: duration_calc = 240 # 4h
             else: duration_calc = 300 # 5h
             
             explain.append(f"🥩 Warsaw (Dual): {request.fat_g}g F, {request.protein_g}g P -> {total_extra_kcal:.0f} kcal")
             explain.append(f"   Equivalente: {fpu_equivalent_carbs:.1f}g x {safety_factor} = {fpu_equivalent_carbs*safety_factor:.1f}g netos")
             explain.append(f"   Extra a Extender: {warsaw_u:.2f} U durante {duration_calc/60:.1f}h")
             
             # Apply Split
             kind = "extended"
             upfront_raw = total_after_exercise # Carbs upfront
             later_raw = warsaw_u # FPU extended
             duration = duration_calc
             
        elif settings.warsaw.enabled and warsaw_u > 0:
             # Add to Upfront
             explain.append(f"🥩 Warsaw (Simple): {total_extra_kcal:.0f} kcal < Umbral {settings.warsaw.trigger_threshold_kcal}.")
             explain.append(f"   Se añade el extra ({warsaw_u:.2f} U) al bolo inmediato.")
             
             kind = "normal"
             upfront_raw = total_after_exercise + warsaw_u
             later_raw = 0.0
        else:
             # Disabled or 0
             upfront_raw = total_after_exercise
             later_raw = 0.0
    else:
        # Standard Normal Bolus
        pct = 1.0
        upfront_raw = total_after_exercise
        later_raw = 0.0
        
    
    # Common final rounding logic for all branches
    if techne_ok:
        upfront = _smart_round(upfront_raw, step, techne_trend, settings.techne.max_step_change, explain)
    else:
        upfront = _round_step(upfront_raw, step)
        
    later = _round_step(later_raw, step)
    
    if later > 0 and later < step:
             explain.append("E) Bolo extendido: la parte extendida es despreciable (< step). Cambiando a Normal.")
             kind = "normal"
             later = 0.0
             # Note: upfront is already rounded from total if it was normal, 
             # but here we might have added FPU insulin that gets lost. 
             # Safety decision: Drop small FPU insulin.
    elif later >= step:
             # Only override kind if it wasn't already extended (though logic above sets it)
             kind = "extended"
             # If duration wasn't set by logic B, use default
             if duration == 0: duration = request.slow_meal.duration_min
             
             explain.append(f"E) Estrategia Dual/Cuadrada (Warsaw/Manual)")
             explain.append(f"   Ahora: {upfront:.2f} U, Luego: {later:.2f} U en {duration} min")


    # 7. Límites finales
    total_final = upfront + later
    if total_final > settings.max_bolus_u:
        warnings.append(f"Bolo total supera máximo de usuario ({settings.max_bolus_u} U). Limitado.")
        ratio = settings.max_bolus_u / total_final
        upfront = _round_step(upfront * ratio, settings.round_step_u)
        later = _round_step(later * ratio, settings.round_step_u)
        total_final = upfront + later 
        explain.append(f"F) Límite de seguridad aplicado: Total ahora {total_final:.2f} U")

    # 7b. Hard Stop por Hipo (Seguridad Crítica)
    if glucose_info.mgdl is not None and glucose_info.mgdl < 70:
        upfront = 0.0
        later = 0.0
        total_final = 0.0
        explain.append(f"⛔ SEGURIDAD: Glucosa < 70 ({glucose_info.mgdl}). Bolo anulado.")
        warnings.append("PELIGRO: Hipo detectada (BG < 70). Bolo cancelado. Trata la hipoglucemia.")

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
