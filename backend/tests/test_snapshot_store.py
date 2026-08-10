from datetime import datetime, timezone

from app.bot.snapshot_store import SnapshotStore
from app.models.bolus_v2 import (
    BolusRequestV2,
    BolusResponseV2,
    GlucoseUsed,
    UsedParams,
)


def test_snapshot_round_trip_restores_bolus_models_after_restart(tmp_path):
    request = BolusRequestV2(carbs_g=30, meal_slot="lunch", target_mgdl=110)
    response = BolusResponseV2(
        meal_bolus_u=3.0,
        correction_u=0.0,
        iob_u=0.5,
        total_u_raw=2.5,
        total_u_final=2.5,
        kind="normal",
        upfront_u=2.5,
        later_u=0.0,
        glucose=GlucoseUsed(mgdl=120, source="dexcom_android"),
        used_params=UsedParams(
            cr_g_per_u=10,
            isf_mgdl_per_u=40,
            target_mgdl=110,
            dia_hours=4,
            max_bolus_final=10,
        ),
        explain=["test"],
    )

    store = SnapshotStore(tmp_path)
    store.set(
        "request-1",
        {
            "rec": response,
            "payload": request,
            "ts": datetime.now(timezone.utc),
        },
    )

    restored = SnapshotStore(tmp_path).get("request-1")

    assert restored is not None
    assert isinstance(restored["rec"], BolusResponseV2)
    assert restored["rec"].total_u_final == 2.5
    assert isinstance(restored["payload"], BolusRequestV2)
    assert restored["payload"].carbs_g == 30
    assert isinstance(restored["ts"], datetime)
