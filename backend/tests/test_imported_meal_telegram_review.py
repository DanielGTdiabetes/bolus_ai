from datetime import datetime, timezone
from types import SimpleNamespace

from app.bot.service import _imported_meal_review_card


def meal(**overrides):
    values = {
        "id": "11111111-1111-1111-1111-111111111111",
        "meal_type": "lunch",
        "last_seen_at": datetime(2026, 8, 22, 13, 32, tzinfo=timezone.utc),
        "foods": [
            {"name": "Pan proteínas", "quantity": "2", "unit": "rebanadas", "carbs_g": 4},
            {"name": "Yogur", "quantity": "1", "unit": "unidad", "carbs_g": 15},
            {"name": "Ensalada", "quantity": "250", "unit": "g", "carbs_g": 8},
        ],
        "source_carbs": 27.0,
        "calculated_carbs": 27.0,
        "validation_error": None,
        "status": "NEW",
        "pending_source_version": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def button_labels(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_review_card_lists_foods_and_does_not_calculate_before_confirmation():
    text, markup = _imported_meal_review_card(meal())

    assert "Pan proteínas" in text
    assert "Yogur" in text
    assert "TOTAL: 27 g HC" in text
    assert "U" not in text
    assert button_labels(markup) == ["✅ Confirmar", "✏️ Editar", "🔄 Actualizar MFP", "🗑 Descartar"]


def test_invalid_review_explains_source_food_mismatch_and_has_no_confirm_button():
    text, markup = _imported_meal_review_card(
        meal(source_carbs=62.0, calculated_carbs=27.0, validation_error="carb_total_mismatch", status="INVALID")
    )

    assert "MyFitnessPal indica: 62 g HC" in text
    assert "Suma de alimentos: 27 g HC" in text
    assert "Diferencia: 35 g HC" in text
    assert "No se calculará ningún bolo" in text
    assert "✅ Confirmar" not in button_labels(markup)


def test_treated_update_shows_only_change_and_prior_bolus_context():
    text, _ = _imported_meal_review_card(meal(
        calculated_carbs=38.0,
        source_carbs=38.0,
        previous_calculated_carbs=27.0,
        status="UPDATED_TREATED",
        last_bolus_units=3.0,
        last_bolus_at=datetime.now(timezone.utc),
    ))

    assert "Anterior: 27 g HC" in text
    assert "Ahora: 38 g HC" in text
    assert "Cambio: +11 g HC" in text
    assert "Bolo previo: 3 U" in text
    assert "solo se evaluará la diferencia pendiente" in text
