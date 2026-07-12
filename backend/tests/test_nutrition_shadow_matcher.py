from datetime import datetime, timedelta, timezone

from app.services.nutrition_shadow_matcher import (
    NutritionShadowEvent,
    classify_nutrition_candidate,
    parse_nutrition_shadow_mode,
)


NOW = datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc)


def event(**overrides) -> NutritionShadowEvent:
    values = {
        "user_id": "admin",
        "occurred_at": NOW,
        "carbs": 30.0,
        "source": "health_connect",
        "fingerprint": "meal-123",
    }
    values.update(overrides)
    return NutritionShadowEvent(**values)


def test_different_users_are_distinct():
    assert classify_nutrition_candidate(event(), event(user_id="other", source="hermes")) == "distinct"


def test_same_timestamp_with_clearly_different_carbs_is_distinct():
    assert classify_nutrition_candidate(event(), event(carbs=45, source="hermes")) == "distinct"


def test_incomplete_data_is_ambiguous():
    assert classify_nutrition_candidate(event(), event(source="hermes", fingerprint=None)) == "ambiguous"


def test_near_equivalent_cross_source_event_is_probable_same_event():
    candidate = event(occurred_at=NOW + timedelta(minutes=3), carbs=30.5, source="hermes")
    assert classify_nutrition_candidate(event(), candidate) == "probable_same_event"


def test_configuration_only_accepts_off_or_shadow():
    assert parse_nutrition_shadow_mode(None) == "off"
    assert parse_nutrition_shadow_mode("off") == "off"
    assert parse_nutrition_shadow_mode("shadow") == "shadow"
    assert parse_nutrition_shadow_mode("unexpected") == "off"
