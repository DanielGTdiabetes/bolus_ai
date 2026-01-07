from datetime import datetime, timedelta, timezone

import pytest

from app.models.schemas import NightscoutSGV, Treatment
from app.services.isf_analysis_service import IsfAnalysisService
from app.services.smart_filter import FilterConfig


class FakeNightscoutClient:
    def __init__(self, treatments, sgv_data):
        self._treatments = treatments
        self._sgv_data = sgv_data

    async def get_recent_treatments(self, hours: int, limit: int = 2000):
        return self._treatments

    async def get_sgv_range(self, start, end, count: int = 5000):
        return self._sgv_data


def build_sgv_series(start_dt: datetime, end_dt: datetime, start_val: int, end_val: int, step_minutes: int = 5):
    total_minutes = int((end_dt - start_dt).total_seconds() / 60)
    steps = max(total_minutes // step_minutes, 1)
    entries = []
    for i in range(steps + 1):
        fraction = i / steps
        val = start_val + (end_val - start_val) * fraction
        ts = start_dt + timedelta(minutes=i * step_minutes)
        entries.append(NightscoutSGV(sgv=int(round(val)), date=ts, direction="Flat"))
    return entries


@pytest.mark.asyncio
async def test_recent_hypo_blocks_decrease(monkeypatch):
    monkeypatch.setattr("app.services.isf_analysis_service.compute_iob", lambda *args, **kwargs: 0.0)
    now = datetime.now(timezone.utc)
    base_time = (now - timedelta(hours=8)).replace(minute=0, second=0, microsecond=0)
    treatments = []
    sgv_data = []

    for days_back in (2, 3, 4):
        t_start = base_time - timedelta(days=days_back)
        t_end = t_start + timedelta(hours=4)
        treatments.append(Treatment(created_at=t_start, insulin=2.0, carbs=0))
        sgv_data.extend(build_sgv_series(t_start, t_end, 200, 140))

    sgv_data.append(NightscoutSGV(sgv=65, date=now - timedelta(hours=2), direction="Flat"))

    client = FakeNightscoutClient(treatments, sgv_data)
    service = IsfAnalysisService(
        client,
        current_cf_settings={"breakfast": 50, "lunch": 50, "dinner": 50},
        profile_settings={"dia_hours": 4, "curve": "walsh", "peak_minutes": 75},
    )

    result = await service.run_analysis("user-1", days=14)

    assert result.blocked_recent_hypo is True
    assert "recent_hypo" in result.global_reason_flags
    assert not any(bucket.suggestion_type == "decrease" for bucket in result.buckets)
    assert any(bucket.status == "blocked_recent_hypo" for bucket in result.buckets)


@pytest.mark.asyncio
async def test_compression_event_is_discarded(monkeypatch):
    monkeypatch.setattr("app.services.isf_analysis_service.compute_iob", lambda *args, **kwargs: 0.0)
    now = datetime.now(timezone.utc)
    t_start = (now - timedelta(hours=10)).replace(minute=0, second=0, microsecond=0)
    t_end = t_start + timedelta(hours=4)
    treatments = [Treatment(created_at=t_start, insulin=1.0, carbs=0)]
    sgv_data = build_sgv_series(t_start, t_end, 180, 120)

    client = FakeNightscoutClient(treatments, sgv_data)
    service = IsfAnalysisService(
        client,
        current_cf_settings={"breakfast": 50, "lunch": 50, "dinner": 50},
        profile_settings={"dia_hours": 4, "curve": "walsh", "peak_minutes": 75},
        compression_config=FilterConfig(enabled=True),
    )

    target_date = sgv_data[len(sgv_data) // 2].date

    def fake_detect(entries, treatments):
        marked = []
        for entry in entries:
            entry = dict(entry)
            if entry["date"] == target_date:
                entry["is_compression"] = True
            marked.append(entry)
        return marked

    monkeypatch.setattr(service.compression_detector, "detect", fake_detect)

    result = await service.run_analysis("user-2", days=14)

    assert result.clean_events
    event = result.clean_events[0]
    assert event.quality_ok is False
    assert "compression" in event.reason_flags


@pytest.mark.asyncio
async def test_insufficient_data_after_filtering(monkeypatch):
    monkeypatch.setattr("app.services.isf_analysis_service.compute_iob", lambda *args, **kwargs: 0.0)
    now = datetime.now(timezone.utc)
    base_time = (now - timedelta(hours=12)).replace(minute=0, second=0, microsecond=0)
    treatments = []
    sgv_data = []

    for days_back in (5, 6):
        t_start = base_time - timedelta(days=days_back)
        t_end = t_start + timedelta(hours=4)
        treatments.append(Treatment(created_at=t_start, insulin=1.0, carbs=0))
        sgv_data.extend(build_sgv_series(t_start, t_end, 190, 150))

    client = FakeNightscoutClient(treatments, sgv_data)
    service = IsfAnalysisService(
        client,
        current_cf_settings={"breakfast": 50, "lunch": 50, "dinner": 50},
        profile_settings={"dia_hours": 4, "curve": "walsh", "peak_minutes": 75},
    )

    result = await service.run_analysis("user-3", days=14)

    assert all(bucket.suggestion_type is None for bucket in result.buckets)
    assert any(bucket.events_count == 2 for bucket in result.buckets)
