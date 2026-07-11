from datetime import datetime

from app.models.treatment import Treatment
from app.services.nutrition_deduplication import (
    external_identity_key,
    macros_equivalent,
    normalize_foods,
    normalize_source,
)


def _row(**overrides) -> Treatment:
    values = {
        "id": "meal",
        "user_id": "user-a",
        "event_type": "Meal Bolus",
        "created_at": datetime(2026, 7, 11, 10, 0),
        "insulin": 0.0,
        "carbs": 20.0,
        "fat": 8.0,
        "protein": 10.0,
        "fiber": 2.0,
        "entered_by": "webhook-integration",
    }
    values.update(overrides)
    return Treatment(**values)


def test_identity_is_scoped_by_user_source_and_external_id():
    base = external_identity_key("user-a", "Health Connect", "event-1")

    assert base == external_identity_key("user-a", "healthconnect", "event-1")
    assert base != external_identity_key("user-b", "Health Connect", "event-1")
    assert base != external_identity_key("user-a", "Hermes Agent", "event-1")
    assert base != external_identity_key("user-a", "Health Connect", "event-2")


def test_food_normalization_is_order_accent_and_case_independent():
    first = normalize_foods(["Café con leche", "Pan Integral"])
    second = normalize_foods(["pan integral", "CAFE CON LECHE"])

    assert first == second


def test_small_rounding_differences_match():
    assert macros_equivalent(
        _row(),
        carbs=20.8,
        fat=7.2,
        protein=10.9,
        fiber=2.0,
    )


def test_macro_difference_outside_tolerance_does_not_match():
    assert not macros_equivalent(
        _row(),
        carbs=22.0,
        fat=8.0,
        protein=10.0,
        fiber=2.0,
    )


def test_missing_optional_macro_is_treated_as_unknown_not_zero():
    assert macros_equivalent(
        _row(fat=0.0, protein=0.0, fiber=0.0),
        carbs=20.0,
        fat=8.0,
        protein=10.0,
        fiber=None,
    )


def test_source_normalization_keeps_hermes_separate_from_health_connect():
    assert normalize_source("Hermes Agent") == "hermes"
    assert normalize_source("MyFitnessPal") == "health_connect"
    assert normalize_source("Health Connect") == "health_connect"
