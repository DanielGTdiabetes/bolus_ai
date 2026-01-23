import logging
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

logger = logging.getLogger(__name__)


def resolve_target(settings: UserSettings, meal_slot: Optional[str]) -> float:
    targets = settings.targets
    slot = meal_slot or "lunch"
    slot_target = getattr(targets, slot, None)
    if slot_target is not None:
        logger.debug("Target resolved from targets.%s=%s", slot, slot_target)
        return float(slot_target)
    if targets.mid is not None:
        logger.debug(
            "Target fallback to targets.mid=%s for slot=%s", targets.mid, slot
        )
        return float(targets.mid)
    logger.debug("Target fallback to default 100 for slot=%s", slot)
    return 100.0

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

    from app.core.constants import EXERCISE_REDUCTION_TABLE
    from app.models.enums import ExerciseIntensity

    # Normalize intensity
    try:
        intens_enum = ExerciseIntensity(intensity.lower())
        intens = intens_enum.value
    except ValueError:
        intens = "moderate"

    points = EXERCISE_REDUCTION_TABLE.get(intens, EXERCISE_REDUCTION_TABLE["moderate"])
    
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
    explain: list[str],
    bg: Optional[float] = None  # Added BG for safety context
) -> float:
    """
    Techne Rounding with Safety Guardrails:
    - Rising (DoubleUp, SingleUp, FortyFiveUp) -> Ceil to step
    - Falling (DoubleDown, SingleDown, FortyFiveDown) -> Floor to step
    - Flat/None -> Nearest (Standard)
    
    Safety Override:
    - If BG < 100, DISABLE 'Ceil' behavior. Enforce 'Floor' or 'Nearest'.
    """
    standard = round(value / step) * step
    
    # Map Trend
    from app.models.enums import Trend
    
    t = trend 
    # Handle Enum objects vs Strings
    if hasattr(t, 'value'):
        t_str = t.value
    else:
        t_str = str(t)
        
    mode = "neutral"
    
    up_trends = [Trend.DOUBLE_UP, Trend.SINGLE_UP, Trend.FORTY_FIVE_UP]
    down_trends = [Trend.DOUBLE_DOWN, Trend.SINGLE_DOWN, Trend.FORTY_FIVE_DOWN]
    
    if any(ut.value.lower() == t_str.lower() for ut in up_trends):
        mode = "up"
    elif any(dt.value.lower() == t_str.lower() for dt in down_trends):
        mode = "down"
    
    # Safety Override: Low BG prevents aggressive rounding up
    if bg is not None and bg < 100 and mode == "up":
        explain.append(f"   (Techne Safety) BG {bg:.0f} < 100: Ignorando redondeo hacia arriba.")
        return standard
        
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


from app.dtos.math_models import CalculationInput, CalculationResult

def _calculate_core(inp: CalculationInput) -> CalculationResult:
    """
    Pure math core. No Pydantic, no HTTP models.
    """
    explain = []
    warnings = []
    
    # --- 1. Autosens ---
    # Calc effective ratio (clamped)
    sug_ratio = inp.autosens_ratio
    if sug_ratio < 0.7: sug_ratio = 0.7
    if sug_ratio > 1.3: sug_ratio = 1.3
    
    effective_ratio = sug_ratio 
    
    # Advice Log
    if abs(effective_ratio - 1.0) > 0.01:
        explain.append(f"🔍 Autosens: Ajustando ratios por {effective_ratio:.2f}x ({inp.autosens_reason or 'Dinámico'})")

    # Appply Autosens (Resistance usually > 1 means need MORE insulin -> Decreased CR/ISF)
    # Factor 1.2 -> CR / 1.2 (Needs less carbs per unit) -> Correct.
    cr = inp.cr / effective_ratio
    isf = inp.isf / effective_ratio
    
    # Safety Guards
    if cr <= 0.1: 
        cr = 10.0
        warnings.append("CR inválido, usando 10.0 g/U")
    if isf <= 5: 
        isf = 30.0
        warnings.append("ISF inválido, usando 30.0 mg/dL/U")
        
    # --- 2. Meal Bolus ---
    meal_u = 0.0
    
    # Fiber Deduction (Net Carbs)
    eff_carbs = inp.carbs_g
    fiber_extension_u = 0.0
    is_high_fiber = False

    if inp.fiber_g >= inp.carbs_g and inp.carbs_g > 0:
        # High Fiber Rule: No deduction.
        # Modified: Do NOT auto-split. User must choose Dual manually if desired.
        explain.append(f"🥗 Fibra Alta ({inp.fiber_g}g >= {inp.carbs_g}g): No se descuenta la fibra. (Recomendado: Valorar Bolo Dual).")
        
    elif inp.use_fiber_deduction and inp.fiber_g > inp.fiber_threshold and inp.carbs_g > 0:
        deduction = inp.fiber_g * inp.fiber_factor
        eff_carbs = max(0.0, inp.carbs_g - deduction)
        explain.append(f"🥗 Fibra ({inp.fiber_g}g > {inp.fiber_threshold}g): Descontados {deduction:.1f}g ({int(inp.fiber_factor*100)}%). Carbos Netos: {eff_carbs:.1f}g")

    if eff_carbs > 0:
        meal_u = eff_carbs / cr
        
        if is_high_fiber:
            # Split 50% to later
            fiber_extension_u = meal_u * 0.5
            meal_u -= fiber_extension_u
            explain.append(f"A) Comida (Fibra Alta): {eff_carbs:.1f}g / {cr:.1f} = {meal_u:.2f} U (Inmediata) + {fiber_extension_u:.2f} U (Extendida)")
        else:
            explain.append(f"A) Comida: {eff_carbs:.1f}g / {cr:.1f} = {meal_u:.2f} U")
    else:
        explain.append("A) Comida: 0g")

    # Warsaw Method (Fat/Protein)
    # Logic:
    # IF Kcal >= Trigger -> DUAL MODE (Factor Dual, Insulin goes to Later/Extended)
    # IF Kcal < Trigger  -> SIMPLE MODE (Factor Simple, Insulin adds to Upfront)
    
    warsaw_later_u = 0.0
    is_split_recommended = False
    
    if inp.warsaw_enabled and (inp.fat_g > 0 or inp.protein_g > 0):
        kcal_fat = inp.fat_g * 9
        kcal_prot = inp.protein_g * 4
        total_kcal = kcal_fat + kcal_prot
        
        # Only apply if significant (> 50kcal)
        if total_kcal > 50:
            fpu_count = total_kcal / 100.0
            
            # Check for Dual Mode (Auto Split)
            # Only if strategy allows it. If 'normal', fallback to Simple
            if total_kcal >= inp.warsaw_trigger and inp.strategy != "normal":
                # --- AUTO DUAL MODE ---
                factor = inp.warsaw_factor_dual
                effective_fpu_carbs = fpu_count * 10.0 * factor
                warsaw_ins = effective_fpu_carbs / cr
                
                # In Dual Mode, Warsaw enters as "Extended" part
                warsaw_later_u = warsaw_ins
                is_split_recommended = True
                
                explain.append(f"   + Warsaw Auto-Dual ({total_kcal:.0f}kcal >= {inp.warsaw_trigger}): {fpu_count:.1f} FPU x {factor:.1f} -> {warsaw_ins:.2f} U (EXTENDIDA)")
                
            else:
                # --- SIMPLE MODE ---
                factor = inp.warsaw_factor_simple
                effective_fpu_carbs = fpu_count * 10.0 * factor
                warsaw_ins = effective_fpu_carbs / cr
                
                # In Simple Mode, Warsaw adds to Upfront (Meal)
                meal_u += warsaw_ins
                
                explain.append(f"   + Warsaw Simple ({total_kcal:.0f}kcal): {fpu_count:.1f} FPU x {factor:.1f} -> {warsaw_ins:.2f} U (INMEDIATA)")

        
    # --- 3. Correction ---
    corr_u = 0.0
    bg_usable = False
    
    if inp.bg_mgdl is not None:
        if inp.bg_is_stale:
            warnings.append(f"Glucosa ({inp.bg_mgdl}) 'stale' (>10min). No corrección.")
            explain.append(f"B) Corrección: DATOS ANTIGUOS. Ignorados.")
        else:
            bg_usable = True
            
    if bg_usable:
        diff = inp.bg_mgdl - inp.target_mgdl
        corr_u = diff / isf
        
        # Max cap
        if corr_u > inp.max_correction_u:
            explain.append(f"   Corrección limitada a {inp.max_correction_u} U (calc: {corr_u:.2f})")
            corr_u = inp.max_correction_u
            
        explain.append(f"B) Corrección: ({inp.bg_mgdl:.0f} - {inp.target_mgdl:.0f}) / {isf:.0f} = {corr_u:.2f} U")
        if inp.bg_mgdl < 70: warnings.append("Glucosa baja. Corrección negativa.")
    else:
        explain.append("B) Corrección: 0 U (Falta glucosa o antigua)")
        
    # --- 4. IOB ---
    # Only reduces Upfront part (Simple)
    total_base_upfront = meal_u + corr_u
    
    if inp.ignore_iob:
        upfront_net = total_base_upfront
        explain.append(f"C) IOB: {inp.iob_u:.2f} U IGNORADO (Estrategia Postre)")
    else:
        upfront_net = max(0.0, total_base_upfront - inp.iob_u)
        if inp.iob_u > 0:
            explain.append(f"C) IOB: {inp.iob_u:.2f} U activos. Neto Upfront: {upfront_net:.2f} U")
        else:
            explain.append("C) IOB: 0 U")
        
    later_base = warsaw_later_u + fiber_extension_u
    if later_base > 0:
        if warsaw_later_u > 0:
            explain.append(f"   (Warsaw Dual): {warsaw_later_u:.2f} U programadas para extensión.")
        if fiber_extension_u > 0:
            explain.append(f"   (Fibra Dual): {fiber_extension_u:.2f} U programadas para extensión.")

    # --- 5. Exercise ---
    final_upfront = upfront_net
    final_later = later_base
    
    if inp.exercise_minutes > 0:
        red = calculate_exercise_reduction(inp.exercise_minutes, inp.exercise_intensity)
        red = min(red, 0.9)
        final_upfront = upfront_net * (1.0 - red)
        final_later = later_base * (1.0 - red)
        explain.append(f"D) Ejercicio ({inp.exercise_intensity} {inp.exercise_minutes}m): -{int(red*100)}%")
        
    # --- 6. Rounding & Limits ---
    # Round separately
    
    # Techne Rounding for Upfront (if enabled and NOT alcohol)
    if inp.techne_enabled and not inp.alcohol_mode and inp.bg_trend:
         final_upfront = _smart_round(final_upfront, inp.round_step, inp.bg_trend, inp.techne_max_step, explain, bg=inp.bg_mgdl)
    else:
         final_upfront = _round_step(final_upfront, inp.round_step)
         
    final_later = _round_step(final_later, inp.round_step)
    
    final_total = final_upfront + final_later
    
    if final_total > inp.max_bolus_u:
        warnings.append(f"Límite Máx {inp.max_bolus_u} U superado (Total).")
        # Scale down proportionally? Or just cap upfront?
        # Safe approach: Cap upfront first.
        excess = final_total - inp.max_bolus_u
        if final_upfront >= excess:
            final_upfront -= excess
        else:
            final_upfront = 0
            final_later = max(0, final_later - (excess - final_upfront))
        final_total = inp.max_bolus_u
        
    # Hard Stop Hipo
    if inp.bg_mgdl and inp.bg_mgdl < 70:
        final_upfront = 0.0
        # Should we cancel later part too? Yes, safety first.
        final_later = 0.0
        final_total = 0.0
        explain.append("⛔ SEGURIDAD: HIPO DETECTADA. BOLO 0.")
        warnings.append("PELIGRO: Hipo. Bolo cancelado.")
        
    return CalculationResult(
        total_u=final_total,
        meal_u=meal_u, # This includes simple warsaw
        corr_u=corr_u,
        breakdown=explain,
        warnings=warnings,
        upfront_u=final_upfront,
        later_u=final_later,
        duration_min=240 if final_later > 0 else 0 # 4 hours default for Warsaw Dual
    )

def calculate_bolus_v2(
    request: BolusRequestV2,
    settings: UserSettings,
    iob_u: float,
    glucose_info: GlucoseUsed,
    autosens_ratio: float = 1.0,
    autosens_reason: Optional[str] = None
) -> BolusResponseV2:
    
    # 1. Adapt Input to Pure DTO (The Bridge)
    meal_slot = request.meal_slot
    cr_base = request.cr_g_per_u or getattr(settings.cr, meal_slot, 10.0)
    isf_base = request.isf_mgdl_per_u or getattr(settings.cf, meal_slot, 30.0)
    if request.target_mgdl is not None:
        target = request.target_mgdl
        logger.debug("Target override from request=%s", target)
    else:
        target = resolve_target(settings, meal_slot)
    
    inp = CalculationInput(
        carbs_g=request.carbs_g,
        fiber_g=request.fiber_g,
        fat_g=request.fat_g,
        protein_g=request.protein_g,
        target_mgdl=target,
        cr=cr_base,
        isf=isf_base,
        bg_mgdl=glucose_info.mgdl,
        bg_trend=glucose_info.trend,
        bg_is_stale=glucose_info.is_stale,
        bg_age_minutes=glucose_info.age_minutes if glucose_info.age_minutes else 0.0,
        iob_u=iob_u,
        autosens_ratio=autosens_ratio,
        autosens_reason=autosens_reason,
        exercise_minutes=request.exercise.minutes if request.exercise.planned else 0,
        exercise_intensity=request.exercise.intensity,
        max_bolus_u=settings.max_bolus_u,
        max_correction_u=settings.max_correction_u,
        round_step=settings.round_step_u,
        use_fiber_deduction=settings.calculator.subtract_fiber,
        fiber_factor=settings.calculator.fiber_factor,
        fiber_threshold=settings.calculator.fiber_threshold_g,
        warsaw_enabled=settings.warsaw.enabled,
        warsaw_factor_simple=request.warsaw_safety_factor or settings.warsaw.safety_factor,
        warsaw_factor_dual=request.warsaw_safety_factor_dual or settings.warsaw.safety_factor_dual,
        warsaw_trigger=request.warsaw_trigger_threshold_kcal or settings.warsaw.trigger_threshold_kcal,
        techne_enabled=settings.techne.enabled,
        techne_max_step=settings.techne.max_step_change,
        ignore_iob=request.ignore_iob,
        alcohol_mode=request.alcohol,
        strategy=request.strategy
    )
    
    # 2. Call Core (Pure Math)
    res = _calculate_core(inp)
    
    # 3. Adapt Output back to Pydantic (Legacy Support)
    # Re-construct some verbose objects for frontend compatibility
    
    used_params = UsedParams(
        cr_g_per_u=round(inp.cr, 1),
        isf_mgdl_per_u=round(inp.isf, 1),
        target_mgdl=target,
        dia_hours=settings.iob.dia_hours,
        insulin_model=settings.iob.curve,
        max_bolus_final=settings.max_bolus_u,
        isf_base=isf_base,
        autosens_ratio=autosens_ratio,
        autosens_reason=autosens_reason,
        config_hash=settings.config_hash
    )

    return BolusResponseV2(
        total_u=res.total_u,
        kind="dual" if res.later_u > 0 else "normal",
        upfront_u=res.upfront_u,
        later_u=res.later_u,
        duration_min=res.duration_min,
        iob_u=round(iob_u, 2),
        meal_bolus_u=round(res.meal_u, 2),
        correction_u=round(res.corr_u, 2),
        total_u_raw=round(res.meal_u + res.corr_u, 2), # Approx
        total_u_final=res.total_u,
        glucose=glucose_info,
        used_params=used_params,
        suggestions=BolusSuggestions(), # Todo restore TDD
        explain=res.breakdown,
        warnings=res.warnings
    )
