from datetime import datetime, timedelta, timezone

import pytest

from app.services.iob import InsulinActionProfile, compute_iob, insulin_activity_fraction


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
