
import pytest
from app.services.smart_filter import CompressionDetector, FilterConfig

# Helper to create mock entries
def mk_entry(sgv, date_ms, direction="Flat"):
    return {
        "sgv": sgv,
        "date": date_ms,
        "direction": direction
    }

def mk_treat(date_ms, insulin=0.0, carbs=0.0):
    return {
        "created_at": None, # or string
        "date": date_ms,
        "insulin": insulin,
        "carbs": carbs
    }

BASE_TIME = 1000000000000

def test_compression_detection_pattern():
    # Detect Drop -> Low -> Rebound
    # Drop 20 in 5 min, Stay low 10 min, Rebound 20 in 10 min
    
    cfg = FilterConfig(enabled=True, night_start_hour=0, night_end_hour=24) # All day for test
    detector = CompressionDetector(cfg)
    
    entries = [
        mk_entry(100, BASE_TIME),
        mk_entry(100, BASE_TIME + 300000),             # 5 min later
        mk_entry(80,  BASE_TIME + 600000),             # Drop -20 in 5m (100->80)
        mk_entry(60,  BASE_TIME + 900000),             # Drop -20 (80->60) -> This is < 70
        mk_entry(62,  BASE_TIME + 1200000),            # Low
        mk_entry(85,  BASE_TIME + 1500000),            # Rebound +23 (62->85) in 5m
        mk_entry(90,  BASE_TIME + 1800000),
    ]
    
    res = detector.detect(entries, [])
    
    # The entry at 60 should be flagged?
    # Drop check: 60. Prev: 80 (diff 20). Time diff 5m. OK.
    # Rebound check: Nexts... 62 (+2), 85 (+25). Diff 10m. OK.
    # So 60 should act as start of trough.
    
    # 60
    assert res[3]['sgv'] == 60
    assert res[3].get('is_compression') is True
    
    # 62 might also be flagged?
    # Drop check: 62. Prev points: 60 (no), 80 (diff 18). Time diff 10m?
    # drop_window is 5m default.
    # 62 - 80 is 10 min ago. Might fail drop window if strict.
    # Our implementation looks back up to window + tolerance.
    
    # Let's check the result
    flagged = [e for e in res if e.get('is_compression')]
    assert len(flagged) >= 1

def test_no_compression_if_treatment_recent():
    cfg = FilterConfig(enabled=True, night_start_hour=0, night_end_hour=24)
    detector = CompressionDetector(cfg)
    
    entries = [
        mk_entry(100, BASE_TIME),
        mk_entry(80,  BASE_TIME + 5*60000),
        mk_entry(60,  BASE_TIME + 10*60000),
        mk_entry(85,  BASE_TIME + 20*60000), 
    ]
    
    # Treatment 5 min before drop
    treatments = [mk_treat(BASE_TIME + 5*60000, insulin=1.0)]
    
    res = detector.detect(entries, treatments)
    flagged = [e for e in res if e.get('is_compression')]
    assert len(flagged) == 0

def test_no_compression_if_daytime_disabled():
    cfg = FilterConfig(enabled=True, night_start_hour=23, night_end_hour=7)
    detector = CompressionDetector(cfg)
    
    # Noon
    NOON = 1702814400000 # 2023-12-17 12:00:00 UTC roughly (Sunday)
    entries = [
        mk_entry(100, NOON),
        mk_entry(60,  NOON + 300000),
        mk_entry(100, NOON + 600000),
    ]
    res = detector.detect(entries, [])
    assert not any(e.get('is_compression') for e in res)

def test_compression_low_flagged_for_fast_drop_and_rebound():
    cfg = FilterConfig(enabled=True, night_start_hour=0, night_end_hour=24)
    detector = CompressionDetector(cfg)

    entries = [
        mk_entry(120, BASE_TIME),
        mk_entry(118, BASE_TIME + 5 * 60000),
        mk_entry(95, BASE_TIME + 10 * 60000),  # Drop 23
        mk_entry(62, BASE_TIME + 15 * 60000),  # Low point
        mk_entry(65, BASE_TIME + 20 * 60000),
        mk_entry(90, BASE_TIME + 25 * 60000),  # Rebound 28
        mk_entry(100, BASE_TIME + 30 * 60000),
    ]

    res = detector.detect(entries, [])
    low_point = res[3]
    assert low_point["sgv"] == 62
    assert low_point.get("is_compression") is True

def test_real_hypo_with_treatment_not_flagged():
    cfg = FilterConfig(enabled=True, night_start_hour=0, night_end_hour=24)
    detector = CompressionDetector(cfg)

    entries = [
        mk_entry(130, BASE_TIME),
        mk_entry(110, BASE_TIME + 5 * 60000),
        mk_entry(85, BASE_TIME + 10 * 60000),
        mk_entry(65, BASE_TIME + 15 * 60000),  # Low after insulin
        mk_entry(58, BASE_TIME + 20 * 60000),
        mk_entry(55, BASE_TIME + 25 * 60000),
        mk_entry(52, BASE_TIME + 30 * 60000),
    ]

    treatments = [mk_treat(BASE_TIME + 10 * 60000, insulin=1.0)]
    res = detector.detect(entries, treatments)
    assert not any(e.get("is_compression") for e in res)
