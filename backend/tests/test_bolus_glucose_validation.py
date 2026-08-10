from datetime import datetime, timezone

import pytest

from app.core.security import CurrentUser
from app.models.bolus_v2 import BolusRequestV2
from app.models.iob import COBInfo, IOBInfo, SourceStatus
from app.services.bolus_calc_service import calculate_bolus_stateless_service
from app.services.glucose_source_service import ResolvedGlucose
from app.services.store import DataStore


def _source_info(now):
    iob = IOBInfo(
        iob_u=0,
        status="ok",
        source="local_db",
        fetched_at=now,
        last_known_iob=0,
        last_updated_at=now,
        treatments_source_status=SourceStatus(source="local_db", status="ok", fetched_at=now),
    )
    cob = COBInfo(cob_g=0, status="ok", model="linear", source="local_db", fetched_at=now)
    return iob, cob


async def _calculate(monkeypatch, tmp_path, resolved, *, manual_bg=None):
    now = datetime.now(timezone.utc)
    iob, cob = _source_info(now)

    async def fake_resolver(*_args, **_kwargs):
        return resolved

    async def fake_iob(*_args, **_kwargs):
        return 0, [], iob, None

    async def fake_cob(*_args, **_kwargs):
        return 0, cob, SourceStatus(source="local_db", status="ok", fetched_at=now)

    async def no_ns_config(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.bolus_calc_service.resolve_current_glucose", fake_resolver)
    monkeypatch.setattr("app.services.bolus_calc_service.compute_iob_from_sources", fake_iob)
    monkeypatch.setattr("app.services.bolus_calc_service.compute_cob_from_sources", fake_cob)
    monkeypatch.setattr("app.services.bolus_calc_service.get_ns_config", no_ns_config)

    return await calculate_bolus_stateless_service(
        BolusRequestV2(
            carbs_g=0,
            bg_mgdl=manual_bg,
            target_mgdl=110,
            cr_g_per_u=10,
            isf_mgdl_per_u=30,
            enable_autosens=False,
        ),
        store=DataStore(tmp_path),
        user=CurrentUser(username="admin", role="admin"),
        session=object(),
    )


@pytest.mark.asyncio
async def test_valid_cgm_reaches_correction_engine(monkeypatch, tmp_path):
    response = await _calculate(
        monkeypatch,
        tmp_path,
        ResolvedGlucose(140, "dexcom_android", "ok", datetime.now(timezone.utc), 2, usable_for_dosing=True),
    )
    assert response.glucose.mgdl == 140
    assert response.correction_u == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["stale", "conflict"])
async def test_unusable_automatic_glucose_cannot_reenter_engine(monkeypatch, tmp_path, status):
    response = await _calculate(
        monkeypatch,
        tmp_path,
        ResolvedGlucose(170, "nightscout", status, datetime.now(timezone.utc), 30, usable_for_dosing=False),
    )
    assert response.glucose.mgdl is None
    assert response.correction_u == 0


@pytest.mark.asyncio
async def test_manual_bg_is_used_without_automatic_source(monkeypatch, tmp_path):
    response = await _calculate(monkeypatch, tmp_path, None, manual_bg=140)
    assert response.glucose.source == "manual"
    assert response.glucose.mgdl == 140
    assert response.correction_u == 1


@pytest.mark.asyncio
async def test_no_bg_produces_no_correction(monkeypatch, tmp_path):
    response = await _calculate(
        monkeypatch,
        tmp_path,
        ResolvedGlucose(None, "none", "unavailable", None, None, usable_for_dosing=False),
    )
    assert response.glucose.mgdl is None
    assert response.correction_u == 0
