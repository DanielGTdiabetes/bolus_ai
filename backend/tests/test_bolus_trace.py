from app.models.bolus_v2 import BolusResponseV2, GlucoseUsed, UsedParams
from app.services.bolus_trace import build_bolus_trace


def test_bolus_trace_keeps_recommended_and_accepted_dose_separate():
    rec = BolusResponseV2(
        total_u=2.0,
        total_u_final=2.0,
        total_u_raw=2.0,
        kind="normal",
        upfront_u=2.0,
        later_u=0.0,
        duration_min=0,
        iob_u=3.5,
        meal_bolus_u=2.0,
        correction_u=0.0,
        glucose=GlucoseUsed(mgdl=110, source="manual", trend="Flat", age_minutes=1),
        used_params=UsedParams(
            cr_g_per_u=10,
            isf_mgdl_per_u=30,
            target_mgdl=110,
            dia_hours=4,
            insulin_model="fiasp",
            max_bolus_final=15,
            config_hash="abc123",
        ),
        explain=["A) Comida: 2.00 U"],
        warnings=[],
    )

    snapshot, ratios, context = build_bolus_trace(
        rec,
        accepted_u=1.5,
        source="app",
    )

    assert snapshot["recommended_u"] == 2.0
    assert snapshot["accepted_u"] == 1.5
    assert snapshot["meal_component_u"] == 2.0
    assert snapshot["iob_u"] == 3.5
    assert snapshot["source"] == "app"
    assert ratios["insulin_model"] == "fiasp"
    assert context["bg"] == 110
    assert context["trend"] == "Flat"
    assert "token" not in str(snapshot).lower()
