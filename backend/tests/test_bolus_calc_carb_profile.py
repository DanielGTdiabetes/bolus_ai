from datetime import datetime, timezone

import pytest

from app.core.security import CurrentUser
from app.models.bolus_v2 import BolusRequestV2, BolusResponseV2, GlucoseUsed, UsedParams
from app.models.iob import COBInfo, IOBInfo, SourceStatus
from app.services.bolus_calc_service import calculate_bolus_stateless_service
from app.services.store import DataStore


@pytest.mark.asyncio
async def test_bolus_calc_passes_carb_profile(monkeypatch, tmp_path):
    called = {}
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

    def fake_calculate_bolus_v2(*, request, settings, iob_u, glucose_info, autosens_ratio, autosens_reason):
        called["carb_profile"] = request.carb_profile
        return BolusResponseV2(
            meal_bolus_u=0.0,
            correction_u=0.0,
            iob_u=0.0,
            total_u_raw=0.0,
            total_u_final=0.0,
            kind="normal",
            upfront_u=0.0,
            later_u=0.0,
            duration_min=0,
            glucose=GlucoseUsed(mgdl=120, source="manual"),
            used_params=UsedParams(
                cr_g_per_u=10,
                isf_mgdl_per_u=50,
                target_mgdl=100,
                dia_hours=4,
                max_bolus_final=10,
            ),
            explain=[],
            warnings=[],
        )

    async def fake_compute_iob_from_sources(*args, **kwargs):
        return 0.0, [], iob_info, None

    async def fake_compute_cob_from_sources(*args, **kwargs):
        return 0.0, cob_info, SourceStatus(source="local_only", status="ok", fetched_at=now)

    monkeypatch.setattr(
        "app.services.bolus_calc_service.compute_iob_from_sources",
        fake_compute_iob_from_sources,
    )
    monkeypatch.setattr(
        "app.services.bolus_calc_service.compute_cob_from_sources",
        fake_compute_cob_from_sources,
    )
    monkeypatch.setattr("app.services.bolus_calc_service.calculate_bolus_v2", fake_calculate_bolus_v2)

    payload = BolusRequestV2(
        carbs_g=30,
        meal_slot="lunch",
        bg_mgdl=120,
        carb_profile="fast",
        confirm_iob_unknown=True,
        confirm_iob_stale=True,
    )

    response = await calculate_bolus_stateless_service(
        payload,
        store=DataStore(tmp_path),
        user=CurrentUser(username="admin", role="admin"),
        session=None,
    )

    assert response.ok is True
    assert called["carb_profile"] == "fast"
