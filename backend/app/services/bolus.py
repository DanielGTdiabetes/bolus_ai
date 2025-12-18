from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.models.settings import UserSettings


@dataclass
class BolusResponse:
    upfront_u: float
    later_u: float
    delay_min: Optional[int]
    iob_u: float
    explain: list[str]
    # Transparency fields
    cr_used: float
    cf_used: float


@dataclass
class BolusRequestData:
    carbs_g: float
    bg_mgdl: Optional[float]
    meal_slot: str
    target_mgdl: Optional[float] = None


def _round_units(value: float, step: float) -> float:
    return round(round(value / step) * step, 2)


def recommend_bolus(request: BolusRequestData, settings: UserSettings, iob_u: float) -> BolusResponse:
    explain: list[str] = []
    meal_slot = request.meal_slot
    
    # Validar Slot
    if meal_slot not in ["breakfast", "lunch", "dinner"]:
        meal_slot = "lunch"
        explain.append(f"Slot '{request.meal_slot}' no válido, usando 'lunch'")

    cr = getattr(settings.cr, meal_slot, 10.0)
    cf = getattr(settings.cf, meal_slot, 30.0)
    target = request.target_mgdl or settings.targets.mid

    # PROTECCION: CR no puede ser 0
    if cr <= 0.1:
        cr = 10.0
        explain.append("CR inválido/cero, forzando 10.0 g/U por seguridad")

    # Fórmula Clave: Bolus = Carbs / CR (g/U)
    carb_units = request.carbs_g / cr
    
    correction_units = 0.0
    bg = request.bg_mgdl
    
    if bg is not None:
        if cf <= 0:
            cf = 30.0 # Safety default
        
        # Enable Reverse Correction (negative result if bg < target)
        correction_units = (bg - target) / cf
        
        # Cap ONLY positive correction
        if correction_units > 0:
            if correction_units > settings.max_correction_u:
                explain.append(f"Corrección positiva limitada a {settings.max_correction_u} U")
                correction_units = settings.max_correction_u
    
    # Calculate tentative total
    # If correction_units is negative, it will reduce the carb_units
    total = carb_units + correction_units - iob_u

    # HYPOGLYCEMIA SAFETY
    if bg is not None:
        if bg < 50:
            explain.append("⛔ GLUCOSA CRÍTICA (< 50): RIESGO GRAVE. Tratar hipoglucemia primero. Bolo cancelado.")
            total = 0.0
        elif bg < 70:
            explain.append("⚠️ Glucosa Baja (50-70): Se aplica corrección negativa. Consumir carbohidratos INMEDIATAMENTE.")
            # We allow the calc (which already has negative correction), but ensure it's not below 0
    
    total = min(total, settings.max_bolus_u)
    if total == settings.max_bolus_u:
        explain.append(f"Bolo limitado a máximo {settings.max_bolus_u} U")

    total = max(total, 0.0)
    step = getattr(settings, "round_step_u", 0.05) or 0.05
    total = _round_units(total, step)

    explain.insert(0, f"Carbs: {request.carbs_g} g / CR {cr} g/U -> {carb_units:.2f} U")
    if bg is not None:
         diff = max(bg - target, 0)
         explain.insert(1, f"Corrección: (BG {bg} - Obj {target}) = {diff:.0f} / CF {cf} -> {correction_units:.2f} U")
    else:
         explain.insert(1, "Corrección: No aplicada (Falta glucosa)")
         
    explain.insert(2, f"IOB restado: {iob_u:.2f} U")

    return BolusResponse(
        upfront_u=total,
        later_u=0.0,
        delay_min=None,
        iob_u=iob_u,
        explain=explain,
        cr_used=cr,
        cf_used=cf
    )
