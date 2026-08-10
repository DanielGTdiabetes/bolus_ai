from __future__ import annotations

from typing import Any, Optional

from app.models.bolus_v2 import BolusResponseV2

TRACE_SCHEMA_VERSION = 1


def build_bolus_trace(
    rec: BolusResponseV2,
    *,
    accepted_u: Optional[float] = None,
    source: Optional[str] = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build a retrospective, non-dosing snapshot of one recommendation.

    The returned dictionaries intentionally contain no credentials, Nightscout
    tokens or other secrets. They exist only to explain/replay what the engine
    used at recommendation time; they must never be treated as future dosing
    inputs.
    """
    glucose = rec.glucose
    used = rec.used_params

    snapshot = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "source": source,
        "recommended_u": rec.total_u_final,
        "accepted_u": accepted_u,
        "kind": rec.kind,
        "meal_component_u": rec.meal_bolus_u,
        "correction_component_u": rec.correction_u,
        "iob_u": rec.iob_u,
        "total_u_raw": rec.total_u_raw,
        "total_u_final": rec.total_u_final,
        "upfront_u": rec.upfront_u,
        "later_u": rec.later_u,
        "duration_min": rec.duration_min,
        "glucose": glucose.model_dump(mode="json") if glucose else None,
        "warnings": list(rec.warnings or []),
        "assumptions": list(rec.assumptions or []),
        "explain": list(rec.explain or []),
    }

    applied_ratios = used.model_dump(mode="json") if used else {}

    context = {
        "bg": glucose.mgdl if glucose else None,
        "trend": glucose.trend if glucose else None,
        "iob": rec.iob_u,
        "glucose_source": glucose.source if glucose else None,
        "glucose_age_minutes": glucose.age_minutes if glucose else None,
        "glucose_is_stale": glucose.is_stale if glucose else None,
    }
    return snapshot, applied_ratios, context
