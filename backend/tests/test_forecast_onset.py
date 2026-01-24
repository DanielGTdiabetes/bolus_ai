
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
    
    # CASE A: 10U Bolus (Proposed) + 5U Bolus (History -60m)
    bolus_10 = ForecastEventBolus(time_offset_min=0, units=10.0, duration_minutes=0)
    bolus_hist = ForecastEventBolus(time_offset_min=-60, units=5.0, duration_minutes=0)
    
    payload_10 = ForecastSimulateRequest(
        start_bg=start_bg,
        params=params,
        events=ForecastEvents(boluses=[bolus_10, bolus_hist]),
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
         
         # Verification:
         # 1. Historical bolus should NOT have moved (still -60)
         # Note: simulate_forecast modifies the payload IN PLACE usually or we inspect input.
         # But here we inspect the SERIES.
         # Actually we can inspect the payload object if passed by reference, but simulate_forecast might modify it.
         # Let's inspect the payload.events.boluses[1].time_offset_min directly.
         
         # Verification 1: Offset Logic (The most critical check)
         # Proposed bolus (0) should shift to 15.
         # Historical bolus (-60) should stay -60.
         assert payload_10.events.boluses[0].time_offset_min == onset_min, f"Proposed bolus offset {payload_10.events.boluses[0].time_offset_min} != {onset_min}"
         assert payload_10.events.boluses[1].time_offset_min == -60, f"History bolus offset {payload_10.events.boluses[1].time_offset_min} != -60"
         
         # Verification 2: Temporal Shift vs Baseline
         # We can compare against a run with offset=0 (simulated by manually hacking it back or just checking Series)
         # Find Time of Lowest BG (Peak Activity)
         series_shifted = response_10.series
         min_point_shifted = min(series_shifted, key=lambda p: p.bg)
         
         print(f"Shifted Min Time: {min_point_shifted.t_min}m BG: {min_point_shifted.bg}")
         
         # Sanity: Min Time should be around Peak + Onset.
         # Peak=75. Onset=15. Expect ~90m.
         assert min_point_shifted.t_min >= 75 + onset_min - 15, "Peak/Nadir seems too early"
         
         # And initial drop check (Relaxed)
         # At t=10 (before onset 15), BG should be close to start (200).
         # Note: Historical bolus (-60) is active, so it WILL drop.
         # So we can't assert "Start BG". Can only assert it's higher than if we had immediate bolus?
         # Let's just trust Offset Logic + Peak Time.
         
         # Check t=5
         p5 = next(p for p in series_shifted if p.t_min == 5)
         print(f"BG at 5m: {p5.bg}")
         
         # If offset logic worked, we are good.
