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
from app.services.math.curves import InsulinCurves, InterpolatedCurves
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


def test_generic_curve_applies_explicit_onset_once():
    params = _params(onset_minutes=15, dia_minutes=60)
    params.insulin_peak_minutes = 30

    assert not InsulinCurves.has_full_timeline(params.insulin_model)
    assert _rapid_insulin_activity(10, params) == 0
    assert _rapid_insulin_activity(20, params) > 0


@pytest.mark.parametrize("model", ["novorapid", "fiasp"])
def test_interpolated_curve_uses_unshifted_elapsed_time(model):
    params = _params(onset_minutes=15, dia_minutes=300)
    params.insulin_model = model
    elapsed_minutes = 20

    expected = InsulinCurves.get_activity(
        elapsed_minutes,
        params.dia_minutes,
        params.insulin_peak_minutes,
        model,
    )

    assert InterpolatedCurves.has_curve(model)
    assert expected > 0
    assert _rapid_insulin_activity(elapsed_minutes, params) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("model", "before_minute", "start_minute"),
    [("fiasp", 0, 1), ("novorapid", 15, 20)],
)
def test_interpolated_curve_onset_matches_tabulated_timeline(
    model, before_minute, start_minute
):
    params = _params(onset_minutes=5 if model == "fiasp" else 15)
    params.insulin_model = model

    assert _rapid_insulin_activity(before_minute, params) == 0
    assert _rapid_insulin_activity(start_minute, params) == pytest.approx(
        InterpolatedCurves.get_activity(model, start_minute, params.dia_minutes)
    )
    assert _rapid_insulin_activity(start_minute, params) > 0


@pytest.mark.parametrize(
    ("model", "tabulated_peak_minute"),
    [("fiasp", 105), ("novorapid", 120)],
)
def test_interpolated_curve_peak_comes_from_table(model, tabulated_peak_minute):
    params = _params(onset_minutes=5 if model == "fiasp" else 15)
    params.insulin_model = model
    samples = {
        minute: _rapid_insulin_activity(minute, params)
        for minute in range(0, params.dia_minutes + 1, 15)
    }

    assert max(samples, key=samples.get) == tabulated_peak_minute


@pytest.mark.parametrize("model", ["novorapid", "fiasp"])
def test_interpolated_curve_still_ends_at_total_dia(model):
    params = _params(onset_minutes=15, dia_minutes=360)
    params.insulin_model = model

    assert _rapid_insulin_activity(359.999, params) > 0
    assert _rapid_insulin_activity(360, params) == 0


@pytest.mark.asyncio
async def test_simulation_endpoint_matches_engine_for_interpolated_curve():
    payload = ForecastSimulateRequest(
        start_bg=200,
        horizon_minutes=60,
        params=_params(onset_minutes=15),
        events=ForecastEvents(
            boluses=[ForecastEventBolus(time_offset_min=-20, units=1)]
        ),
        momentum=MomentumConfig(enabled=False),
    )
    payload.params.insulin_model = "novorapid"
    expected = ForecastEngine.calculate_forecast(payload.model_copy(deep=True))
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    with patch("app.api.forecast.get_ns_config", return_value=None), patch(
        "app.api.forecast.get_user_settings_service", return_value=None
    ):
        response = await simulate_forecast(
            payload, user=MagicMock(username="testuser"), session=session
        )

    assert response.components == expected.components


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


@pytest.mark.parametrize("model", ["fiasp", "novorapid"])
def test_backend_does_not_resolve_external_onset_for_full_timeline(model):
    params = _params(onset_minutes=5 if model == "fiasp" else 15)
    params.insulin_model = model
    settings = MagicMock()
    settings.insulin.name = model

    resolve_insulin_action_params(params, settings)

    assert params.insulin_onset_minutes is None


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
