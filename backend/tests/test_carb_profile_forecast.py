from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.api import forecast as forecast_api
from app.core.db import get_db_session_context
from app.core.security import CurrentUser
from app.models.forecast import (
    ForecastEvents,
    ForecastPoint,
    ForecastResponse,
    ForecastSimulateRequest,
    ForecastSummary,
    SimulationParams,
)
from app.models.treatment import Treatment


@pytest.mark.asyncio
async def test_treatment_carb_profile_persists_and_enriches_forecast(monkeypatch):
    now = datetime.now(timezone.utc)
    treatment_id = "treatment-carb-profile-1"

    async with get_db_session_context() as session:
        treatment = Treatment(
            id=treatment_id,
            user_id="admin",
            event_type="Meal Bolus",
            created_at=now.replace(tzinfo=None),
            insulin=0.0,
            carbs=45.0,
            fat=10.0,
            protein=15.0,
            fiber=5.0,
            carb_profile="slow",
            notes="Unit test",
            entered_by="unit-test",
            is_uploaded=False,
        )
        session.add(treatment)
        await session.commit()

        row = (await session.execute(select(Treatment).where(Treatment.id == treatment_id))).scalar_one()
        assert row.carb_profile == "slow"

        def fake_calculate_forecast(req):
            return ForecastResponse(
                series=[ForecastPoint(t_min=0, bg=req.start_bg)],
                summary=ForecastSummary(
                    bg_now=req.start_bg,
                    min_bg=req.start_bg,
                    max_bg=req.start_bg,
                    ending_bg=req.start_bg,
                ),
            )

        monkeypatch.setattr(forecast_api.ForecastEngine, "calculate_forecast", fake_calculate_forecast)

        payload = ForecastSimulateRequest(
            start_bg=110,
            params=SimulationParams(
                isf=50,
                icr=10,
                dia_minutes=300,
                carb_absorption_minutes=180,
                insulin_peak_minutes=75,
                insulin_model="linear",
                target_bg=100,
            ),
            events=ForecastEvents(),
        )
        await forecast_api.simulate_forecast(
            payload,
            user=CurrentUser(username="admin", role="admin"),
            session=session,
        )

        assert any(evt.carb_profile == "slow" for evt in payload.events.carbs)
