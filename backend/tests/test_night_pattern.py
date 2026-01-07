from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.settings import NightPatternConfig
from app.models.forecast import ForecastPoint
from app.services.night_pattern import (
    NightPatternBucketStats,
    NightPatternContext,
    NightPatternProfileData,
    apply_night_pattern_adjustment,
)


LOCAL_TZ = ZoneInfo("Europe/Madrid")


def _base_context(**overrides) -> NightPatternContext:
    base = dict(
        draft_active=False,
        meal_recent=False,
        bolus_recent=False,
        iob_u=0.1,
        cob_g=0.0,
        trend_slope=0.1,
        sustained_rise=False,
        slow_digestion_signal=False,
        last_meal_high_fat_protein=False,
    )
    base.update(overrides)
    return NightPatternContext(**base)


def _pattern_for_time(now_local: datetime) -> NightPatternProfileData:
    bucket_key = f"{now_local.hour:02d}:{(now_local.minute // 15) * 15:02d}"
    return NightPatternProfileData(
        buckets={
            bucket_key: NightPatternBucketStats(median_delta=20.0, dispersion=5.0, sample_points=12)
        },
        sample_days=18,
        sample_points=120,
        computed_at=datetime.utcnow(),
        bucket_minutes=15,
        horizon_minutes=75,
        source="nightscout",
    )


def test_pattern_never_applies_after_disable_time():
    cfg = NightPatternConfig(enabled=True)
    now_local = datetime(2026, 2, 10, 4, 0, tzinfo=LOCAL_TZ)
    pattern = _pattern_for_time(now_local)
    series = [ForecastPoint(t_min=0, bg=120.0)]
    adjusted, meta, _ = apply_night_pattern_adjustment(series, pattern, cfg, now_local, _base_context())
    assert adjusted == series
    assert meta["applied"] is False


def test_pattern_applies_in_window_a_when_clean():
    cfg = NightPatternConfig(enabled=True)
    now_local = datetime(2026, 2, 10, 1, 0, tzinfo=LOCAL_TZ)
    pattern = _pattern_for_time(now_local)
    series = [ForecastPoint(t_min=0, bg=120.0)]
    adjusted, meta, _ = apply_night_pattern_adjustment(series, pattern, cfg, now_local, _base_context())
    assert meta["applied"] is True
    assert adjusted[0].bg == 126.0


def test_pattern_blocked_in_window_b_with_slow_digestion_signal():
    cfg = NightPatternConfig(enabled=True)
    now_local = datetime(2026, 2, 10, 2, 30, tzinfo=LOCAL_TZ)
    pattern = _pattern_for_time(now_local)
    series = [ForecastPoint(t_min=0, bg=120.0)]
    context = _base_context(slow_digestion_signal=True)
    adjusted, meta, _ = apply_night_pattern_adjustment(series, pattern, cfg, now_local, context)
    assert adjusted == series
    assert meta["applied"] is False


def test_pattern_disables_if_iob_or_cob_unavailable():
    cfg = NightPatternConfig(enabled=True)
    now_local = datetime(2026, 2, 10, 1, 30, tzinfo=LOCAL_TZ)
    pattern = _pattern_for_time(now_local)
    series = [ForecastPoint(t_min=0, bg=120.0)]
    context = _base_context(iob_u=None)
    adjusted, meta, _ = apply_night_pattern_adjustment(series, pattern, cfg, now_local, context)
    assert adjusted == series
    assert meta["applied"] is False


def test_pattern_clamp_respects_cap():
    cfg = NightPatternConfig(enabled=True, cap_mgdl=25.0)
    now_local = datetime(2026, 2, 10, 1, 15, tzinfo=LOCAL_TZ)
    bucket_key = f"{now_local.hour:02d}:{(now_local.minute // 15) * 15:02d}"
    pattern = NightPatternProfileData(
        buckets={
            bucket_key: NightPatternBucketStats(median_delta=200.0, dispersion=5.0, sample_points=12)
        },
        sample_days=18,
        sample_points=120,
        computed_at=datetime.utcnow(),
        bucket_minutes=15,
        horizon_minutes=75,
        source="nightscout",
    )
    series = [ForecastPoint(t_min=0, bg=120.0)]
    adjusted, meta, _ = apply_night_pattern_adjustment(series, pattern, cfg, now_local, _base_context())
    assert meta["applied"] is True
    assert adjusted[0].bg == 145.0
