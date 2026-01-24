
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
    
    # CASE A: 10U Bolus
    bolus_10 = ForecastEventBolus(time_offset_min=0, units=10.0, duration_minutes=0)
    
    payload_10 = ForecastSimulateRequest(
        start_bg=start_bg,
        params=params,
        events=ForecastEvents(boluses=[bolus_10]),
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
         series_10 = response_10.series
         
         # Check t=0
         p0 = next(p for p in series_10 if p.t_min == 0)
         assert abs(p0.bg - start_bg) < 1.0
         
         # Check t=10 (Scenario: Onset 15m).
         # At 10m, we are BEFORE onset. Drop should be minimal (essentially 0 if basal is perfectly balanced or ignored)
         # In simulate_forecast, basal defaults to compensating drift if not provided.
         
         p10 = next(p for p in series_10 if p.t_min == 10)
         drop_10m = start_bg - p10.bg
         print(f"Drop at 10m (Onset={onset_min}): {drop_10m} mg/dL")
         
         # Allow tiny noise but SHOULD be < 2-3 mg/dL. Before fix it was ~20.
         assert drop_10m < 5.0, f"Drop at 10m {drop_10m} is significant despite 15m onset"
         
         # Check t=20 (After Onset). Should see drop starting.
         p20 = next(p for p in series_10 if p.t_min == 20)
         drop_20m = start_bg - p20.bg
         print(f"Drop at 20m: {drop_20m} mg/dL")
         assert drop_20m > drop_10m + 1.0, "Curve should start dropping after onset"
         
         
         # CASE B: 6U vs 12U
         params.insulin_onset_minutes = 10 # Change onset to 10 for diversity
         bolus_6 = ForecastEventBolus(time_offset_min=0, units=6.0)
         payload_6 = ForecastSimulateRequest(start_bg=200, params=params, events=ForecastEvents(boluses=[bolus_6]), momentum=MomentumConfig(enabled=False))
         
         bolus_12 = ForecastEventBolus(time_offset_min=0, units=12.0)
         payload_12 = ForecastSimulateRequest(start_bg=200, params=params, events=ForecastEvents(boluses=[bolus_12]), momentum=MomentumConfig(enabled=False))
         
         resp_6 = await simulate_forecast(payload_6, user=mock_user, session=mock_session)
         resp_12 = await simulate_forecast(payload_12, user=mock_user, session=mock_session)
         
         min_6 = resp_6.summary.min_bg
         min_12 = resp_12.summary.min_bg
         
         print(f"Min 6U: {min_6}, Min 12U: {min_12}")
         
         assert min_12 < min_6 - 10.0, "12U should drop much more than 6U"
         
         # Ensure shapes are different (min time might be similar, but depth different)
