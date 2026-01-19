from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import CurrentUser, get_current_user
from app.main import app
from app.models.iob import COBInfo, IOBInfo, SourceStatus


@pytest.mark.asyncio
async def test_api_bolus_calc_accepts_exercise_params():
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(username="admin", role="admin")
    try:
        now = datetime.now(timezone.utc)
        iob_info = IOBInfo(
            iob_u=0.0,
            status="ok",
            reason=None,
            source="local_only",
            fetched_at=now,
            last_known_iob=0.0,
            last_updated_at=now,
            treatments_source_status=SourceStatus(source="local_only", status="ok", fetched_at=now),
            assumptions=[],
        )
        cob_info = COBInfo(
            cob_g=0.0,
            status="ok",
            model="linear",
            assumptions=[],
            source="local_only",
            reason=None,
            fetched_at=now,
        )
        with patch(
            "app.services.bolus_calc_service.compute_iob_from_sources",
            return_value=(0.0, [], iob_info, None),
        ), patch(
            "app.services.bolus_calc_service.compute_cob_from_sources",
            return_value=(0.0, cob_info, SourceStatus(source="local_only", status="ok", fetched_at=now)),
        ):
            payload = {
                "carbs_g": 30,
                "meal_slot": "lunch",
                "bg_mgdl": 120,
                "exercise": {"planned": True, "minutes": 30, "intensity": "moderate"},
                "confirm_iob_unknown": True,
                "confirm_iob_stale": True,
            }
            resp = client.post("/api/bolus/calc", json=payload)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["ok"] is True
            assert any("Ejercicio" in line for line in body["explain"])
    finally:
        app.dependency_overrides = {}
