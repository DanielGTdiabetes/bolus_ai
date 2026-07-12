import ast
import inspect
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.forecast import get_current_forecast, simulate_forecast
from app.models.forecast import (
    ForecastEventBolus,
    ForecastEventCarbs,
    ForecastEvents,
    ForecastSimulateRequest,
    MomentumConfig,
    SimulationParams,
)


async def _run_simulation(payload: ForecastSimulateRequest):
    mock_user = MagicMock()
    mock_user.username = "testuser"
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    with patch("app.api.forecast.get_ns_config", return_value=None), patch(
        "app.api.forecast.get_user_settings_service", return_value=None
    ):
        return await simulate_forecast(payload, user=mock_user, session=mock_session)


def _simulation_params(*, onset, model="linear") -> SimulationParams:
    return SimulationParams(
        isf=50,
        icr=10,
        dia_minutes=300,
        carb_absorption_minutes=180,
        insulin_peak_minutes=75,
        insulin_model=model,
        insulin_onset_minutes=onset,
    )

@pytest.mark.asyncio
async def test_insulin_onset_delay_logic():
    """
    Test that insulin_onset_minutes shifts the bolus action and prevents immediate drops.
    """
    onset_min = 15
    start_bg = 200.0
    isf = 50.0
    
    params = SimulationParams(
        isf=isf, 
        icr=10, 
        dia_minutes=300, # 5h
        carb_absorption_minutes=180, 
        insulin_peak_minutes=75, 
        insulin_model="linear", 
        insulin_onset_minutes=onset_min
    )
    
    # CASE A: 10U Bolus (Proposed, 0m), 5U (History, -60m), 5U (Future, +10m)
    bolus_10 = ForecastEventBolus(time_offset_min=0, units=10.0, duration_minutes=0)
    bolus_hist = ForecastEventBolus(time_offset_min=-60, units=5.0, duration_minutes=0)
    bolus_future = ForecastEventBolus(time_offset_min=10, units=5.0, duration_minutes=0)
    
    payload_10 = ForecastSimulateRequest(
        start_bg=start_bg,
        params=params,
        events=ForecastEvents(boluses=[bolus_10, bolus_hist, bolus_future]),
        momentum=MomentumConfig(enabled=False)
    )
    
    mock_user = MagicMock()
    mock_user.username = "testuser"
    mock_session = AsyncMock()
    
    # Configure DB Mock to return empty list
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result
    
    with patch("app.api.forecast.get_ns_config", return_value=None), \
         patch("app.api.forecast.get_user_settings_service", return_value=None):
         
         # We need to rely on the REAL ForecastEngine to calculate curves.
         # This assumes ForecastEngine is unit-testable and does not depend on DB/External calls
         # other than what's passed in payload (which it mostly does).
         
         # 1. Run Simulation
         response_10 = await simulate_forecast(payload_10, user=mock_user, session=mock_session)
         
         # Verification 1: Offset Logic
         # Bolus 0 (0m) -> Should Stay 0
         # Bolus 1 (-60m) -> Should Stay -60
         # Bolus 2 (+10m) -> Should Shift +15 -> +25
         
         assert payload_10.events.boluses[0].time_offset_min == 0, f"Current bolus shifted to {payload_10.events.boluses[0].time_offset_min}!"
         assert payload_10.events.boluses[1].time_offset_min == -60, "History bolus changed!"
         assert payload_10.events.boluses[2].time_offset_min == 10 + onset_min, f"Future bolus not shifted! Got {payload_10.events.boluses[2].time_offset_min}"
         
         # Verification 2: Temporal Shift
         # Just check that min point exists and is reasonably placed (not testing exact physics here)
         series_shifted = response_10.series
         min_point_shifted = min(series_shifted, key=lambda p: p.bg)
         
         print(f"Min Time: {min_point_shifted.t_min}m BG: {min_point_shifted.bg}")
         assert min_point_shifted.t_min > 30, "Peak seems too early for insulin action"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset", "expected"),
    [(-60, -60), (-2, -2), (-1, -1), (0, 0), (1, 16), (10, 25)],
)
async def test_onset_applies_only_to_future_offsets(offset, expected):
    payload = ForecastSimulateRequest(
        start_bg=150,
        horizon_minutes=60,
        params=_simulation_params(onset=15),
        events=ForecastEvents(
            boluses=[ForecastEventBolus(time_offset_min=offset, units=1.0)]
        ),
        momentum=MomentumConfig(enabled=False),
    )

    await _run_simulation(payload)

    assert payload.events.boluses[0].time_offset_min == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("onset", "expected_offset"),
    [(None, 20), (0, 10), (5, 15), (15, 25)],
)
async def test_future_bolus_receives_onset_exactly_once(onset, expected_offset):
    payload = ForecastSimulateRequest(
        start_bg=150,
        horizon_minutes=60,
        params=_simulation_params(onset=onset),
        events=ForecastEvents(
            boluses=[ForecastEventBolus(time_offset_min=10, units=1.0)]
        ),
        momentum=MomentumConfig(enabled=False),
    )

    await _run_simulation(payload)

    assert payload.events.boluses[0].time_offset_min == expected_offset


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["linear", "fiasp", "novorapid"])
@pytest.mark.parametrize("duration_minutes", [0, 120])
@pytest.mark.parametrize("with_carbs", [False, True])
async def test_onset_preserves_event_data_across_supported_scenarios(
    model, duration_minutes, with_carbs
):
    carbs = [ForecastEventCarbs(time_offset_min=0, grams=20)] if with_carbs else []
    payload = ForecastSimulateRequest(
        start_bg=150,
        horizon_minutes=60,
        params=_simulation_params(onset=15, model=model),
        events=ForecastEvents(
            boluses=[
                ForecastEventBolus(
                    time_offset_min=0,
                    units=1.0,
                    duration_minutes=duration_minutes,
                ),
                ForecastEventBolus(
                    time_offset_min=10,
                    units=2.0,
                    duration_minutes=duration_minutes,
                ),
            ],
            carbs=carbs,
        ),
        momentum=MomentumConfig(enabled=False),
    )
    original_carbs = [carb.model_dump() for carb in payload.events.carbs]

    await _run_simulation(payload)

    assert [bolus.time_offset_min for bolus in payload.events.boluses] == [0, 25]
    assert [bolus.units for bolus in payload.events.boluses] == [1.0, 2.0]
    assert [bolus.duration_minutes for bolus in payload.events.boluses] == [
        duration_minutes,
        duration_minutes,
    ]
    assert [carb.model_dump() for carb in payload.events.carbs] == original_carbs


def _has_future_only_onset_guard(function) -> bool:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    for onset_guard in ast.walk(tree):
        if not (
            isinstance(onset_guard, ast.If)
            and isinstance(onset_guard.test, ast.Compare)
            and isinstance(onset_guard.test.left, ast.Name)
            and onset_guard.test.left.id == "onset_val"
            and len(onset_guard.test.ops) == 1
            and isinstance(onset_guard.test.ops[0], ast.Gt)
        ):
            continue

        for loop in onset_guard.body:
            if not (
                isinstance(loop, ast.For)
                and isinstance(loop.target, ast.Name)
                and loop.target.id == "bolus"
            ):
                continue

            for future_guard in loop.body:
                if not (
                    isinstance(future_guard, ast.If)
                    and isinstance(future_guard.test, ast.Compare)
                    and isinstance(future_guard.test.left, ast.Attribute)
                    and isinstance(future_guard.test.left.value, ast.Name)
                    and future_guard.test.left.value.id == "bolus"
                    and future_guard.test.left.attr == "time_offset_min"
                    and len(future_guard.test.ops) == 1
                    and isinstance(future_guard.test.ops[0], ast.Gt)
                    and len(future_guard.test.comparators) == 1
                    and isinstance(future_guard.test.comparators[0], ast.Constant)
                    and future_guard.test.comparators[0].value == 0
                ):
                    continue

                return any(
                    isinstance(statement, ast.AugAssign)
                    and isinstance(statement.target, ast.Attribute)
                    and isinstance(statement.target.value, ast.Name)
                    and statement.target.value.id == "bolus"
                    and statement.target.attr == "time_offset_min"
                    and isinstance(statement.op, ast.Add)
                    and isinstance(statement.value, ast.Name)
                    and statement.value.id == "onset_val"
                    for statement in future_guard.body
                )

    return False


def test_current_and_simulate_share_future_only_onset_guard():
    assert _has_future_only_onset_guard(get_current_forecast)
    assert _has_future_only_onset_guard(simulate_forecast)
