from typing import Optional
from app.models.settings import UserSettings
from app.models.forecast import SimulationParams

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
