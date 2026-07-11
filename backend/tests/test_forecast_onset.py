from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.api.forecast import simulate_forecast
from app.models.forecast import (
    ForecastEventBolus,
    ForecastEvents,
    ForecastSimulateRequest,
    MomentumConfig,
    SimulationParams,
)
from app.services.forecast_engine import ForecastEngine, _rapid_insulin_activity
from app.services.forecast_params_resolver import resolve_insulin_action_params


def _params(*, onset_minutes: int = 15, dia_minutes: int = 300) -> SimulationParams:
    return SimulationParams(
        isf=50,
        icr=10,
        dia_minutes=dia_minutes,
        carb_absorption_minutes=180,
        insulin_peak_minutes=75,
        insulin_model="linear",
        insulin_onset_minutes=onset_minutes,
    )


def _single_bolus_forecast(*, onset_minutes: int, dia_minutes: int = 60):
    params = _params(onset_minutes=onset_minutes, dia_minutes=dia_minutes)
    params.insulin_peak_minutes = 30
    request = ForecastSimulateRequest(
        start_bg=200,
        horizon_minutes=dia_minutes + 10,
        step_minutes=5,
        params=params,
        events=ForecastEvents(boluses=[ForecastEventBolus(units=1)]),
        momentum=MomentumConfig(enabled=False),
    )
    return ForecastEngine.calculate_forecast(request)


@pytest.mark.asyncio
async def test_insulin_onset_delay_logic():
    """The API preserves event time; the engine applies onset exactly once."""
    payload = ForecastSimulateRequest(
        start_bg=200,
        params=_params(onset_minutes=15),
        events=ForecastEvents(
            boluses=[
                ForecastEventBolus(time_offset_min=0, units=10),
                ForecastEventBolus(time_offset_min=-60, units=5),
                ForecastEventBolus(time_offset_min=10, units=5),
            ]
        ),
        momentum=MomentumConfig(enabled=False),
    )
    original_offsets = [bolus.time_offset_min for bolus in payload.events.boluses]
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    with patch("app.api.forecast.get_ns_config", return_value=None), patch(
        "app.api.forecast.get_user_settings_service", return_value=None
    ):
        response = await simulate_forecast(payload, user=MagicMock(username="testuser"), session=session)

    assert [bolus.time_offset_min for bolus in payload.events.boluses] == original_offsets
    assert response.components


def test_activity_starts_at_onset_and_ends_at_total_dia():
    params = _params(onset_minutes=15, dia_minutes=60)
    params.insulin_peak_minutes = 30

    assert _rapid_insulin_activity(14.999, params) == 0
    assert _rapid_insulin_activity(15, params) == 0
    assert _rapid_insulin_activity(15.001, params) > 0
    assert _rapid_insulin_activity(59.999, params) > 0
    assert _rapid_insulin_activity(60, params) == 0


def test_forecast_onset_zero_and_nonzero_use_same_minute_contract():
    no_onset = _single_bolus_forecast(onset_minutes=0)
    delayed = _single_bolus_forecast(onset_minutes=15)

    assert no_onset.components[1].insulin_impact < 0
    assert delayed.components[1].insulin_impact == 0
    assert delayed.components[3].insulin_impact == 0
    assert delayed.components[4].insulin_impact < 0
    assert delayed.components[-1].insulin_impact == delayed.components[-2].insulin_impact


def test_backend_resolves_onset_once_from_insulin_settings():
    params = _params(onset_minutes=0)
    params.insulin_onset_minutes = None
    settings = MagicMock()
    settings.insulin.name = "NovoRapid"

    resolve_insulin_action_params(params, settings)
    resolve_insulin_action_params(params, settings)

    assert params.insulin_onset_minutes == 15


def test_backend_rejects_resolved_onset_outside_total_dia():
    params = _params(onset_minutes=0, dia_minutes=10)
    params.insulin_onset_minutes = None
    settings = MagicMock()
    settings.insulin.name = "NovoRapid"

    with pytest.raises(ValueError, match="lower than dia_minutes"):
        resolve_insulin_action_params(params, settings)


def test_onset_must_be_nonnegative_and_lower_than_total_dia():
    with pytest.raises(ValidationError):
        _params(onset_minutes=-1)
    with pytest.raises(ValidationError):
        _params(onset_minutes=60, dia_minutes=60)
