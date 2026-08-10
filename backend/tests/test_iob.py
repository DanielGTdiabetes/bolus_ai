from datetime import datetime, timedelta, timezone

import pytest

from app.models.settings import UserSettings
from app.models.schemas import Treatment as NightscoutTreatment
from app.services.iob import (
    InsulinActionProfile,
    _merge_unique_boluses,
    compute_iob,
    compute_iob_from_sources,
    insulin_activity_fraction,
)
from app.services.store import DataStore


def test_iob_bilinear_basic():
    now = datetime.now(timezone.utc)
    profile = InsulinActionProfile(dia_hours=4, curve="bilinear", peak_minutes=60)
    bolus = {"ts": now.isoformat(), "units": 10.0}

    iob_now = compute_iob(now, [bolus], profile)
    assert iob_now == pytest.approx(10.0, rel=1e-4)

    end_time = now + timedelta(hours=profile.dia_hours)
    iob_end = compute_iob(end_time, [bolus], profile)
    assert iob_end == pytest.approx(0.0, abs=1e-4)

    checkpoints = [0, 30, 60, 90, 120, 150, 180, 210, 240]
    values = [
        compute_iob(now + timedelta(minutes=mins), [bolus], profile)
        for mins in checkpoints
    ]
    assert values == sorted(values, reverse=True)


def test_insulin_activity_fraction_monotonic():
    profile = InsulinActionProfile(dia_hours=4, curve="walsh", peak_minutes=75)
    fractions = [
        insulin_activity_fraction(minute, profile)
        for minute in range(0, int(profile.dia_hours * 60) + 1, 30)
    ]
    assert fractions[0] == pytest.approx(1.0)
    assert fractions[-1] == pytest.approx(0.0)
    assert fractions == sorted(fractions, reverse=True)


@pytest.mark.parametrize("curve,peak", [("walsh", 75), ("fiasp", 55)])
def test_supported_iob_curves_are_used(curve, peak):
    profile = InsulinActionProfile(dia_hours=4, curve=curve, peak_minutes=peak)
    fraction = insulin_activity_fraction(30, profile)
    assert 0 < fraction < 1


def test_multiple_boluses_all_contribute_to_iob():
    now = datetime.now(timezone.utc)
    records = [
        {"id": "one", "ts": (now - timedelta(minutes=20)).isoformat(), "units": 2},
        {"id": "two", "ts": (now - timedelta(minutes=60)).isoformat(), "units": 2},
    ]
    total = compute_iob(now, records, InsulinActionProfile(4, "walsh", 75))
    assert total > 2


def test_distinct_stable_ids_are_never_deduped_by_dose_or_time():
    records = [
        {"id": f"bolus-{minute}", "ts": f"2026-01-01T{hour:02d}:{minute_in_hour:02d}:00+00:00", "units": 2}
        for minute, hour, minute_in_hour in ((0, 8, 0), (20, 8, 20), (60, 9, 0), (120, 10, 0))
    ]
    assert len(_merge_unique_boluses(records)) == 4


def test_same_stable_identity_is_a_real_duplicate():
    local = {"id": "local-1", "nightscout_id": "ns-1", "ts": "2026-01-01T08:00:00Z", "units": 2}
    mirror = {"id": "ns-1", "ts": "2026-01-01T08:00:00Z", "units": 2}
    assert _merge_unique_boluses([local], [mirror]) == [local]


def test_legacy_dedupe_requires_exact_timestamp_and_dose():
    first = {"ts": "2026-01-01T08:00:00Z", "units": 2}
    exact_mirror = {"ts": "2026-01-01T08:00:00+00:00", "units": 2}
    later = {"ts": "2026-01-01T08:01:00Z", "units": 2}
    assert _merge_unique_boluses([first], [exact_mirror, later]) == [first, later]


@pytest.mark.parametrize("legacy_first", [True, False])
def test_legacy_exact_mirror_dedupes_against_identified_record(legacy_first):
    stable = {"id": "stable", "ts": "2026-01-01T08:00:00Z", "units": 2}
    legacy = {"ts": "2026-01-01T08:00:00+00:00", "units": 2}
    sources = ([legacy], [stable]) if legacy_first else ([stable], [legacy])
    assert len(_merge_unique_boluses(*sources)) == 1


@pytest.mark.asyncio
async def test_source_failure_never_becomes_zero_ok(monkeypatch, tmp_path):
    async def failed_sources(**_kwargs):
        return [], [], [], "database offline", None, None

    monkeypatch.setattr("app.services.iob._load_iob_sources", failed_sources)
    value, _breakdown, info, _warning = await compute_iob_from_sources(
        datetime.now(timezone.utc),
        UserSettings(),
        None,
        DataStore(tmp_path),
        persist_cache=False,
    )
    assert value is None
    assert info.iob_u is None
    assert info.status == "unavailable"


@pytest.mark.asyncio
async def test_empty_successful_sources_are_a_real_zero(monkeypatch, tmp_path):
    async def empty_sources(**_kwargs):
        return [], [], [], None, None, None

    monkeypatch.setattr("app.services.iob._load_iob_sources", empty_sources)
    value, breakdown, info, warning = await compute_iob_from_sources(
        datetime.now(timezone.utc),
        UserSettings(),
        None,
        DataStore(tmp_path),
        persist_cache=False,
    )
    assert value == 0
    assert breakdown == []
    assert info.status == "ok"
    assert warning is None


@pytest.mark.asyncio
async def test_identified_external_bolus_is_used_when_not_local(tmp_path):
    now = datetime.now(timezone.utc)

    class Nightscout:
        async def get_recent_treatments(self, **_kwargs):
            return [NightscoutTreatment(
                _id="external-bolus-1",
                eventType="Correction Bolus",
                created_at=now - timedelta(minutes=15),
                insulin=2,
            )]

    value, breakdown, info, warning = await compute_iob_from_sources(
        now,
        UserSettings(),
        Nightscout(),
        DataStore(tmp_path),
        user_id="external-source-test",
        persist_cache=False,
    )
    assert value is not None and value > 0
    assert [item["id"] for item in breakdown] == ["external-bolus-1"]
    assert "nightscout" in info.source
    assert warning is None


@pytest.mark.asyncio
async def test_unidentified_external_insulin_is_not_silently_ignored(tmp_path):
    now = datetime.now(timezone.utc)

    class Nightscout:
        async def get_recent_treatments(self, **_kwargs):
            return [NightscoutTreatment(
                eventType="Correction Bolus",
                created_at=now - timedelta(minutes=15),
                insulin=2,
            )]

    value, _breakdown, info, _warning = await compute_iob_from_sources(
        now,
        UserSettings(),
        Nightscout(),
        DataStore(tmp_path),
        user_id="external-source-test",
        persist_cache=False,
    )
    assert value is None
    assert info.status == "unavailable"
