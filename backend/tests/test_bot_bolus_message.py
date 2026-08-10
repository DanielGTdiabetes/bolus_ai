from types import SimpleNamespace

from app.bot.service import _build_bolus_message


def _rec(*, meal=2.0, correction=0.0, iob=0.0, total=2.0, target=110.0):
    return SimpleNamespace(
        total_u_final=total,
        meal_bolus_u=meal,
        correction_u=correction,
        iob_u=iob,
        used_params=SimpleNamespace(target_mgdl=target),
        explain=[],
    )


def test_bot_message_does_not_present_iob_as_subtracted_from_new_carbs():
    text, _, _ = _build_bolus_message(
        _rec(meal=2.0, correction=0.0, iob=3.5, total=2.0),
        carbs=20,
        fat=0,
        protein=0,
        bg_val=110,
        request_id="abc123",
        notes="",
    )

    assert "IOB activo: 3.50 U" in text
    assert "aplicado a corrección: 0.00 U" in text
    assert "IOB: −3.50 U" not in text
    assert "Ajuste/Redondeo" not in text


def test_bot_message_reports_only_iob_actually_allocated_to_positive_correction():
    text, _, _ = _build_bolus_message(
        _rec(meal=2.0, correction=2.0, iob=1.0, total=3.0),
        carbs=20,
        fat=0,
        protein=0,
        bg_val=170,
        request_id="abc124",
        notes="",
    )

    assert "IOB activo: 1.00 U" in text
    assert "aplicado a corrección: 1.00 U" in text
    assert "corrección restante: 1.00 U" in text


def test_bot_message_zero_iob_is_described_as_active_state_not_subtraction():
    text, _, _ = _build_bolus_message(
        _rec(meal=2.0, correction=0.0, iob=0.0, total=2.0),
        carbs=20,
        fat=0,
        protein=0,
        bg_val=110,
        request_id="abc125",
        notes="",
    )

    assert "IOB activo: 0.00 U" in text
    assert "IOB: −0.0 U" not in text
