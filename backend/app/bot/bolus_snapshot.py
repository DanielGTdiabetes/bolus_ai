from __future__ import annotations

from typing import Any

from app.models.bolus_v2 import BolusRequestV2


def build_slot_recalc_payload(snapshot: dict[str, Any], slot: str) -> BolusRequestV2:
    """Rebuild a bot bolus request when the user changes meal slot.

    Modern snapshots keep their original request context, changing only the
    selected slot. Legacy snapshots are rebuilt from meal facts only. Persistent
    dosing configuration (target, ICR, ISF, insulin model, limits and Autosens)
    remains intentionally absent so the central backend resolves the current
    authoritative settings for the selected slot.
    """
    base_payload = snapshot.get("payload")
    if isinstance(base_payload, BolusRequestV2):
        request = base_payload.model_copy(deep=True)
        request.meal_slot = slot
        # A snapshot may originate from an older client that embedded a target.
        # Changing slot must never retain a target from the previous slot.
        request.target_mgdl = None
        request.cr_g_per_u = None
        request.isf_mgdl_per_u = None
        request.dia_hours = None
        request.insulin_model = None
        request.insulin_peak_minutes = None
        request.round_step_u = None
        request.max_bolus_u = None
        request.enable_autosens = None
        return request

    return BolusRequestV2(
        carbs_g=float(snapshot.get("carbs", 0) or 0),
        fat_g=float(snapshot.get("fat", 0) or 0),
        protein_g=float(snapshot.get("protein", 0) or 0),
        fiber_g=float(snapshot.get("fiber", 0) or 0),
        meal_slot=slot,
    )
