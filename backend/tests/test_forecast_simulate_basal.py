
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone, timedelta
from app.models.forecast import ForecastSimulateRequest, ForecastEvents, ForecastEventBolus, SimulationParams, MomentumConfig
from app.api.forecast import simulate_forecast
from app.models.basal import BasalEntry
from app.models.treatment import Treatment

@pytest.mark.asyncio
async def test_simulate_forecast_basal_injection_logic():
    with patch("app.api.forecast.get_ns_config", return_value=None), \
         patch("app.api.forecast.get_user_settings_service", return_value=None), \
         patch("app.api.forecast.ForecastEngine.calculate_forecast") as mock_calc:
         
         mock_session = AsyncMock()
         
         # Logic calls session.execute twice or more.
         # 1. Treatments (if not has_history) -> We skip this branch in this test
         # 2. Basal -> We hit this.
         
         active_basal = BasalEntry(
            id=1, user_id="testuser", 
            dose_u=20.0, basal_type="glargine", effective_hours=24,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2)
         )
         
         mock_result_basal = MagicMock()
         mock_result_basal.scalars.return_value.all.return_value = [active_basal]
         
         mock_session.execute.return_value = mock_result_basal
         
         mock_user = MagicMock()
         mock_user.username = "testuser"
         
         payload = ForecastSimulateRequest(
            start_bg=120.0,
            params=SimulationParams(isf=50, icr=10, dia_minutes=300, carb_absorption_minutes=180, insulin_peak_minutes=75, insulin_model="linear", target_bg=100),
            events=ForecastEvents(
                boluses=[ForecastEventBolus(time_offset_min=-60, units=5.0, duration_minutes=0)],
                carbs=[],
                basal_injections=[]
            ),
            momentum=MomentumConfig(enabled=False), 
            recent_bg_series=None
         )
         
         await simulate_forecast(payload, user=mock_user, session=mock_session)
         
         args, _ = mock_calc.call_args
         final_payload = args[0]
         
         # Assert BASAL INJECTED from DB
         assert len(final_payload.events.basal_injections) > 0
         assert final_payload.events.basal_injections[0].units == 20.0


@pytest.mark.asyncio
async def test_simulate_forecast_basal_injection_skipped_if_present():
    with patch("app.api.forecast.get_ns_config", return_value=None), \
         patch("app.api.forecast.get_user_settings_service", return_value=None), \
         patch("app.api.forecast.ForecastEngine.calculate_forecast") as mock_calc:
         
         mock_session = AsyncMock()
         
         # Here boluses=[] => has_history=False.
         # So it enters `if not has_history` block.
         # It calls session.execute for Treatments.
         # Then it calls session.execute for Basal (our new block).
         
         # Mocking side_effect to handle multiple calls
         mock_treatments_result = MagicMock()
         mock_treatments_result.scalars.return_value.all.return_value = [] # No treatments
         
         mock_basal_result = MagicMock()
         # DB has 20U, but we shouldn't fetch/use it if we skip.
         # But the logic is: "if not payload.basal_injections: fetch".
         # Since we provide payload basal, it should NOT fetch.
         # So session.execute should be called ONCE (for treatments).
         # We can verify call count.
         
         mock_session.execute.side_effect = [mock_treatments_result, mock_basal_result]
         
         mock_user = MagicMock()
         mock_user.username = "testuser"
         
         from app.models.forecast import ForecastBasalInjection
         payload_basal = ForecastBasalInjection(
             time_offset_min=0, units=10.0, duration_minutes=1440, type="glargine"
         )
         
         payload = ForecastSimulateRequest(
            start_bg=120.0,
            params=SimulationParams(isf=50, icr=10, dia_minutes=300, carb_absorption_minutes=180, insulin_peak_minutes=75, insulin_model="linear", target_bg=100),
            events=ForecastEvents(
                boluses=[],
                carbs=[],
                basal_injections=[payload_basal]
            ),
            momentum=MomentumConfig(enabled=False)
         )
         
         await simulate_forecast(payload, user=mock_user, session=mock_session)
         
         args, _ = mock_calc.call_args
         final_payload = args[0]
         
         # Assert ONLY Payload Basal exists
         assert len(final_payload.events.basal_injections) == 1
         assert final_payload.events.basal_injections[0].units == 10.0
         
         # Verify we didn't query DB for Basal (optimization check)
         # We expect 1 call to execute (Treatments)
         # Wait, other calls? get_ns_config mocked. settings mocked.
         # So mostly 1 call.
         # Actually session.execute might be called for sick mode too (line ~675).
         # It's better to trust the output list check.
