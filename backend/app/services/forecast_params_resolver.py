from typing import Optional
from app.models.settings import UserSettings
from app.models.forecast import SimulationParams
from app.services.math.curves import InsulinCurves

def resolve_warsaw_params(
    params: SimulationParams,
    user_settings: Optional[UserSettings]
) -> None:
    """
    Resolve Warsaw parameters in a single, authoritative place.
    ForecastEngine must never receive undefined or implicit Warsaw params.
    """

    # Trigger kcal
    if params.warsaw_trigger is None:
        if user_settings and user_settings.warsaw:
            params.warsaw_trigger = user_settings.warsaw.trigger_threshold_kcal
        else:
            params.warsaw_trigger = 50  # Safe default (matches /current)

    # Simple factor
    if params.warsaw_factor_simple is None:
        if user_settings and user_settings.warsaw and user_settings.warsaw.enabled:
            params.warsaw_factor_simple = user_settings.warsaw.safety_factor
        else:
            # FULL conversion by default, never 0.1
            params.warsaw_factor_simple = 1.0


def resolve_insulin_action_params(
    params: SimulationParams,
    user_settings: Optional[UserSettings],
) -> None:
    """Resolve the simulation's minute-based insulin action contract once."""
    if InsulinCurves.has_full_timeline(params.insulin_model):
        # Interpolated curves own onset and peak from injection through DIA.
        params.insulin_onset_minutes = None
        return

    if params.insulin_onset_minutes is not None:
        return

    insulin_name = ""
    if user_settings and user_settings.insulin:
        insulin_name = (user_settings.insulin.name or "").lower()

    if "fiasp" in insulin_name or "lyumjev" in insulin_name:
        onset_minutes = 5
    elif any(name in insulin_name for name in ("novorapid", "aspart", "humalog", "lispro", "apidra")):
        onset_minutes = 15
    else:
        onset_minutes = 10

    if onset_minutes >= params.dia_minutes:
        raise ValueError("resolved insulin onset must be lower than dia_minutes")
    params.insulin_onset_minutes = onset_minutes
