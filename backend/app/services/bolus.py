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


@dataclass
class BolusRequestData:
    carbs_g: float
    bg_mgdl: float
    meal_slot: str
    target_mgdl: Optional[float] = None


def _round_units(value: float, step: float) -> float:
    return round(value / step) * step


def recommend_bolus(request: BolusRequestData, settings: UserSettings, iob_u: float) -> BolusResponse:
    explain: list[str] = []
    meal_slot = request.meal_slot
    cr = getattr(settings.cr, meal_slot)
    cf = getattr(settings.cf, meal_slot)
    target = request.target_mgdl or settings.targets.mid

    carb_units = request.carbs_g / cr if cr else 0.0
    correction_units = 0.0
    if request.bg_mgdl > target + 5:
        correction_units = (request.bg_mgdl - target) / cf if cf else 0.0

    correction_cap = min(max(correction_units, 0.0), settings.max_correction_u)
    if correction_cap < correction_units:
        explain.append(f"Corrección limitada a {settings.max_correction_u} U")
    correction_units = correction_cap

    total = carb_units + correction_units - iob_u

    if request.bg_mgdl < 70:
        explain.append("BG < 70 mg/dL: sin corrección; recomendamos 0 U")
        total = 0.0
    total = min(total, settings.max_bolus_u)
    if total == settings.max_bolus_u:
        explain.append(f"Bolo limitado a máximo {settings.max_bolus_u} U")

    total = max(total, 0.0)
    step = getattr(settings, "round_step_u", 0.05) or 0.05
    total = _round_units(total, step)

    explain.insert(0, f"Carbohidratos: {request.carbs_g} g / CR {cr} -> {carb_units:.2f} U")
    explain.insert(1, f"Corrección: {max(request.bg_mgdl - target, 0):.0f} / CF {cf} -> {correction_units:.2f} U")
    explain.insert(2, f"IOB restado: {iob_u:.2f} U")

    return BolusResponse(
        upfront_u=total,
        later_u=0.0,
        delay_min=None,
        iob_u=iob_u,
        explain=explain,
    )
