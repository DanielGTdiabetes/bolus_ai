import pytest

from app.models.settings import UserSettings
from app.services.autosens_hybrid import (
    build_compression_config,
    combine_hybrid_autosens,
)


def test_build_compression_config_matches_user_settings():
    settings = UserSettings.default()
    settings.nightscout.filter_compression = True
    settings.nightscout.filter_night_start = "22:00"
    settings.nightscout.filter_night_end = "06:00"
    settings.nightscout.treatments_lookback_minutes = 150

    config = build_compression_config(settings)

    assert config.enabled is True
    assert config.night_start_hour == 22
    assert config.night_end_hour == 6
    assert config.treatments_lookback_minutes == 150


def test_hybrid_multiplies_components_and_clamps():
    decision = combine_hybrid_autosens(
        tdd_ratio=1.10,
        local_ratio=1.05,
        min_ratio=0.70,
        max_ratio=1.20,
    )
    assert decision.blocked is False
    assert decision.raw_ratio == pytest.approx(1.155)
    assert decision.ratio == pytest.approx(1.155)

    clamped = combine_hybrid_autosens(
        tdd_ratio=1.20,
        local_ratio=1.20,
        min_ratio=0.70,
        max_ratio=1.20,
    )
    assert clamped.raw_ratio == pytest.approx(1.44)
    assert clamped.ratio == pytest.approx(1.20)


def test_recent_hypo_guardrail_neutralizes_entire_hybrid():
    decision = combine_hybrid_autosens(
        tdd_ratio=1.20,
        local_ratio=1.0,
        min_ratio=0.70,
        max_ratio=1.20,
        local_reason_flags=["recent_hypos"],
    )
    assert decision.blocked is True
    assert decision.ratio == 1.0
    assert decision.blocking_flags == ("recent_hypos",)


def test_local_exception_fails_neutral_instead_of_tdd_only():
    decision = combine_hybrid_autosens(
        tdd_ratio=1.20,
        local_ratio=1.0,
        min_ratio=0.70,
        max_ratio=1.20,
        local_error="RuntimeError: local calculation failed",
    )
    assert decision.blocked is True
    assert decision.ratio == 1.0


def test_insufficient_local_data_does_not_masquerade_as_guardrail():
    decision = combine_hybrid_autosens(
        tdd_ratio=1.10,
        local_ratio=1.0,
        min_ratio=0.70,
        max_ratio=1.20,
        local_reason_flags=["insufficient_data"],
    )
    assert decision.blocked is False
    assert decision.ratio == pytest.approx(1.10)


def test_invalid_bounds_are_rejected():
    with pytest.raises(ValueError):
        combine_hybrid_autosens(
            tdd_ratio=1.0,
            local_ratio=1.0,
            min_ratio=1.2,
            max_ratio=0.7,
        )
