from app.bot.bolus_snapshot import build_slot_recalc_payload
from app.models.bolus_v2 import BolusRequestV2


def assert_server_side_dosing_fields_are_unset(payload: BolusRequestV2) -> None:
    assert payload.target_mgdl is None
    assert payload.cr_g_per_u is None
    assert payload.isf_mgdl_per_u is None
    assert payload.dia_hours is None
    assert payload.insulin_model is None
    assert payload.insulin_peak_minutes is None
    assert payload.round_step_u is None
    assert payload.max_bolus_u is None
    assert payload.enable_autosens is None
    assert payload.nightscout is None


def test_legacy_snapshot_rebuilds_meal_facts_without_dosing_overrides():
    payload = build_slot_recalc_payload(
        {
            "carbs": 35,
            "fat": 12,
            "protein": 20,
            "fiber": 4,
        },
        "dinner",
    )

    assert payload.meal_slot == "dinner"
    assert payload.carbs_g == 35
    assert payload.fat_g == 12
    assert payload.protein_g == 20
    assert payload.fiber_g == 4
    assert_server_side_dosing_fields_are_unset(payload)


def test_modern_snapshot_drops_previous_slot_dosing_overrides():
    old_payload = BolusRequestV2(
        carbs_g=20,
        fat_g=10,
        protein_g=15,
        fiber_g=3,
        meal_slot="breakfast",
        target_mgdl=105,
        cr_g_per_u=5,
        isf_mgdl_per_u=30,
        dia_hours=4,
        insulin_model="fiasp",
        insulin_peak_minutes=55,
        round_step_u=0.5,
        max_bolus_u=15,
        enable_autosens=False,
    )

    payload = build_slot_recalc_payload({"payload": old_payload}, "lunch")

    assert payload.meal_slot == "lunch"
    assert payload.carbs_g == 20
    assert payload.fat_g == 10
    assert payload.protein_g == 15
    assert payload.fiber_g == 3
    assert_server_side_dosing_fields_are_unset(payload)
