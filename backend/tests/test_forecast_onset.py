
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from app.api.forecast import simulate_forecast
from app.models.forecast import ForecastSimulateRequest, ForecastEvents, ForecastEventBolus, SimulationParams, MomentumConfig

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
