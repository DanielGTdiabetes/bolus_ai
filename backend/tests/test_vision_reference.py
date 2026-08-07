from app.services.vision import _parse_estimation_data


def test_vision_uses_item_ranges_and_pen_evidence():
    result = _parse_estimation_data({
        "items": [
            {"name": "Arroz", "carbs_g": 40, "carbs_range_g": [32, 48], "confidence": "medium"},
            {"name": "Salsa", "carbs_g": 6, "carbs_range_g": [3, 10], "confidence": "low"},
        ],
        "confidence": "medium",
        "reference": {
            "used": True,
            "type": "insulin_pen",
            "confidence": "medium",
            "pen_fully_visible": True,
            "same_plane_confidence": "medium",
        },
    })

    assert result.carbs_estimate_g == 46
    assert result.carbs_range_g == (35, 58)
    assert result.reference_type == "insulin_pen"
    assert result.pen_fully_visible is True


def test_explicit_weight_overrides_visual_reference():
    result = _parse_estimation_data(
        {"items": [{"name": "Pan", "carbs_g": 20}], "confidence": "low"},
        {"plate_weight_grams": 50},
    )
    assert result.reference_used is True
    assert result.reference_type == "scale"
    assert result.reference_confidence == "high"
