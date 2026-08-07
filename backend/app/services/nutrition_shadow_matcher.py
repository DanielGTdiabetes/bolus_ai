import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional


NutritionMatchClassification = Literal["distinct", "ambiguous", "probable_same_event"]
NutritionShadowMode = Literal["off", "shadow"]


@dataclass(frozen=True)
class NutritionShadowEvent:
    user_id: Optional[str]
    occurred_at: Optional[datetime]
    carbs: Optional[float]
    source: Optional[str]
    fingerprint: Optional[str]


def parse_nutrition_shadow_mode(value: Optional[str]) -> NutritionShadowMode:
    return "shadow" if value == "shadow" else "off"


def extract_import_fingerprint(notes: Optional[str]) -> Optional[str]:
    prefix = "Imported from Health: "
    suffix = " #imported"
    if not notes or prefix not in notes or suffix not in notes:
        return None
    fingerprint = notes.split(prefix, 1)[1].split(suffix, 1)[0].strip()
    return fingerprint or None


def _source_family(source: str) -> Optional[str]:
    normalized = source.strip().lower()
    if "hermes" in normalized:
        return "hermes"
    if any(name in normalized for name in ("health connect", "health_connect", "myfitnesspal")):
        return "health_connect"
    return None


def classify_nutrition_candidate(
    incoming: NutritionShadowEvent,
    candidate: NutritionShadowEvent,
) -> NutritionMatchClassification:
    if incoming.user_id and candidate.user_id and incoming.user_id != candidate.user_id:
        return "distinct"

    required = (
        incoming.user_id,
        candidate.user_id,
        incoming.occurred_at,
        candidate.occurred_at,
        incoming.carbs,
        candidate.carbs,
        incoming.source,
        candidate.source,
        incoming.fingerprint,
        candidate.fingerprint,
    )
    if any(value is None for value in required):
        return "ambiguous"

    incoming_source = _source_family(incoming.source)
    candidate_source = _source_family(candidate.source)
    if not incoming_source or not candidate_source or incoming_source == candidate_source:
        return "ambiguous"

    incoming_carbs = float(incoming.carbs)
    candidate_carbs = float(candidate.carbs)
    if (
        not math.isfinite(incoming_carbs)
        or not math.isfinite(candidate_carbs)
        or incoming_carbs < 0
        or candidate_carbs < 0
    ):
        return "ambiguous"
    if abs(incoming_carbs - candidate_carbs) > 1.0:
        return "distinct"

    def as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    time_delta = abs((as_utc(incoming.occurred_at) - as_utc(candidate.occurred_at)).total_seconds())
    if time_delta > 20 * 60:
        return "distinct"

    if incoming.fingerprint != candidate.fingerprint:
        return "ambiguous"

    return "probable_same_event"
