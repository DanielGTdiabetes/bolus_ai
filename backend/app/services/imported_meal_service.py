from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.imported_meal import ImportedMeal, ImportedMealSnapshot


CARB_TOLERANCE_G = 1.0
VALID_STATES = {
    "NEW", "UNCHANGED", "UPDATED_UNTREATED", "UPDATED_TREATED", "INVALID",
    "CONFIRMED", "DISCARDED",
}
_LEGACY_REFERENCE_RE = re.compile(
    r"^(hermes-mfp:\d{4}-\d{2}-\d{2}:[^:]+):[0-9a-f]{16,64}$",
    re.IGNORECASE,
)
MEAL_SLOT_ALIASES = {
    "breakfast": "breakfast",
    "desayuno": "breakfast",
    "lunch": "lunch",
    "comida": "lunch",
    "almuerzo": "lunch",
    "dinner": "dinner",
    "cena": "dinner",
    "snack": "snack",
    "snacks": "snack",
    "merienda": "snack",
    "aperitivos": "snack",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _number(value: object) -> float:
    try:
        return float(Decimal(str(value or 0)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


def normalize_meal_type(value: object) -> str:
    normalized = str(value or "unknown").strip().lower()
    return MEAL_SLOT_ALIASES.get(normalized, normalized)


def normalize_foods(raw_foods: object) -> list[dict[str, Any]]:
    if not isinstance(raw_foods, list):
        return []
    foods: list[dict[str, Any]] = []
    for raw in raw_foods:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name") or raw.get("short_name") or "").strip()
        if not name:
            continue
        foods.append({
            "name": name[:200],
            "quantity": str(raw.get("quantity") or raw.get("amount") or "").strip()[:80],
            "unit": str(raw.get("unit") or "").strip()[:40],
            "carbs_g": _number(raw.get("carbs_g", raw.get("carbs"))),
            "fat_g": _number(raw.get("fat_g", raw.get("fat"))),
            "protein_g": _number(raw.get("protein_g", raw.get("protein"))),
            "fiber_g": _number(raw.get("fiber_g", raw.get("fiber"))),
        })
    return foods


def calculated_carbs(foods: list[dict[str, Any]]) -> float:
    return _number(sum(_number(food.get("carbs_g")) for food in foods))


def content_fingerprint(
    *, foods: list[dict[str, Any]], source_carbs: float, fat: float, protein: float, fiber: float
) -> str:
    canonical = {
        "foods": foods,
        "source_carbs": _number(source_carbs),
        "fat": _number(fat),
        "protein": _number(protein),
        "fiber": _number(fiber),
    }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stable_source_reference(payload: Mapping[str, Any]) -> str:
    explicit = str(payload.get("meal_id") or payload.get("source_reference") or "").strip()
    legacy = _LEGACY_REFERENCE_RE.match(explicit)
    if legacy:
        return legacy.group(1).lower()
    if explicit:
        return explicit[:255]
    meal_date = str(payload.get("date") or "").strip()
    meal_type = normalize_meal_type(payload.get("meal") or payload.get("meal_type"))
    return f"hermes-mfp:{meal_date}:{meal_type}"[:255]


def parse_meal_date(value: object) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ValueError("invalid_meal_date")


def _validation_error(source_carbs: float, foods: list[dict[str, Any]]) -> str | None:
    if not foods:
        return "missing_food_items"
    summed = calculated_carbs(foods)
    if abs(source_carbs - summed) > CARB_TOLERANCE_G:
        return "carb_total_mismatch"
    return None


@dataclass(frozen=True)
class ReconciliationResult:
    meal: ImportedMeal
    state: str
    should_notify: bool
    created: bool
    previous_carbs: float | None = None


async def reconcile_imported_meal(
    session: AsyncSession,
    *,
    user_id: str,
    payload: Mapping[str, Any],
    sync_id: str | None,
) -> ReconciliationResult:
    """Normalize and reconcile one MFP candidate without ever dosing from it."""
    now = _utc_now()
    source = str(payload.get("source") or payload.get("provider") or "MyFitnessPal-Hermes").strip()[:80]
    source_reference = stable_source_reference(payload)
    meal_day = parse_meal_date(payload.get("date"))
    meal_type = normalize_meal_type(payload.get("meal") or payload.get("meal_type"))[:40]
    foods = normalize_foods(payload.get("foods"))
    source_carbs = _number(payload.get("source_carbs", payload.get("carbs")))
    summed_carbs = calculated_carbs(foods)
    fat = _number(payload.get("fat"))
    protein = _number(payload.get("protein"))
    fiber = _number(payload.get("fiber"))
    fingerprint = str(payload.get("meal_revision") or payload.get("fingerprint") or "").strip()
    if not fingerprint:
        fingerprint = content_fingerprint(
            foods=foods, source_carbs=source_carbs, fat=fat, protein=protein, fiber=fiber
        )
    else:
        fingerprint = hashlib.sha256(f"external:{fingerprint}".encode()).hexdigest()
    validation_error = _validation_error(source_carbs, foods)
    source_stable = bool(payload.get("stability_confirmed")) and int(payload.get("stable_read_count") or 0) >= 2

    meal = (
        await session.execute(
            select(ImportedMeal).where(
                ImportedMeal.user_id == user_id,
                ImportedMeal.source == source,
                ImportedMeal.source_reference == source_reference,
            )
        )
    ).scalars().first()
    created = meal is None
    previous_carbs: float | None = None

    if meal is None:
        meal = ImportedMeal(
            user_id=user_id,
            source=source,
            source_reference=source_reference,
            meal_date=meal_day,
            meal_type=meal_type,
            foods=foods,
            source_carbs=source_carbs,
            calculated_carbs=summed_carbs,
            fat=fat,
            protein=protein,
            fiber=fiber,
            fingerprint=fingerprint,
            stable_read_count=2 if source_stable else 1,
            is_stable=source_stable,
            validation_error=validation_error or (None if source_stable else "awaiting_stability"),
            status="INVALID" if validation_error or not source_stable else "NEW",
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(meal)
        await session.flush()
        state = meal.status
        should_notify = source_stable
    else:
        previous_carbs = float(meal.calculated_carbs or 0)
        meal.last_seen_at = now
        if meal.manual_override and fingerprint != meal.fingerprint:
            previous_pending = dict(meal.pending_source_version or {})
            meal.status = "UPDATED_TREATED" if meal.treatment_status == "TREATED" else "UPDATED_UNTREATED"
            state = meal.status
            if meal.rejected_source_fingerprint == fingerprint:
                meal.pending_source_version = None
                should_notify = False
            else:
                pending_changed = previous_pending.get("fingerprint") != fingerprint
                previous_pending_stable = bool(previous_pending.get("is_stable"))
                pending_read_count = (
                    2 if source_stable else
                    (int(previous_pending.get("stable_read_count") or 0) + 1 if not pending_changed else 1)
                )
                pending_is_stable = source_stable or pending_read_count >= 2
                meal.pending_source_version = {
                    "fingerprint": fingerprint,
                    "foods": foods,
                    "source_carbs": source_carbs,
                    "calculated_carbs": summed_carbs,
                    "fat": fat,
                    "protein": protein,
                    "fiber": fiber,
                    "validation_error": validation_error,
                    "stable_read_count": pending_read_count,
                    "is_stable": pending_is_stable,
                }
                if pending_changed:
                    meal.version = int(meal.version or 0) + 1
                should_notify = pending_is_stable and (pending_changed or not previous_pending_stable)
        elif fingerprint == meal.fingerprint:
            meal.stable_read_count = max(int(meal.stable_read_count or 0) + 1, 2 if source_stable else 0)
            was_stable = meal.is_stable
            meal.is_stable = was_stable or source_stable or meal.stable_read_count >= 2
            meal.validation_error = validation_error or (None if meal.is_stable else "awaiting_stability")
            if meal.discarded_fingerprint == fingerprint:
                meal.status = "DISCARDED"
                should_notify = False
            elif validation_error:
                should_notify = meal.status != "INVALID"
                meal.status = "INVALID"
            elif not was_stable and meal.is_stable:
                meal.status = "NEW"
                should_notify = True
            else:
                meal.status = "UNCHANGED"
                should_notify = False
            state = meal.status
        else:
            meal.previous_fingerprint = meal.fingerprint
            meal.previous_calculated_carbs = meal.calculated_carbs
            meal.fingerprint = fingerprint
            meal.version = int(meal.version or 0) + 1
            meal.foods = foods
            meal.source_carbs = source_carbs
            meal.calculated_carbs = summed_carbs
            meal.fat = fat
            meal.protein = protein
            meal.fiber = fiber
            meal.manual_override = False
            meal.pending_source_version = None
            meal.stable_read_count = 2 if source_stable else 1
            meal.is_stable = source_stable
            meal.validation_error = validation_error or (None if source_stable else "awaiting_stability")
            if validation_error or not source_stable:
                meal.status = "INVALID"
            else:
                meal.status = "UPDATED_TREATED" if meal.treatment_status == "TREATED" else "UPDATED_UNTREATED"
            state = meal.status
            should_notify = source_stable

        session.add(meal)
        await session.flush()

    session.add(ImportedMealSnapshot(
        meal_id=meal.id,
        sync_id=sync_id,
        fingerprint=fingerprint,
        source_carbs=source_carbs,
        calculated_carbs=summed_carbs,
        foods=foods,
        validation_error=validation_error,
        timing=dict(payload.get("timing") or {}) or None,
    ))
    await session.execute(
        delete(ImportedMealSnapshot).where(
            ImportedMealSnapshot.seen_at < now - timedelta(days=7)
        )
    )
    await session.flush()
    return ReconciliationResult(meal, state, should_notify, created, previous_carbs)


async def edit_food(
    session: AsyncSession, *, meal_id: str, index: int, carbs: float | None = None,
    quantity: str | None = None,
) -> ImportedMeal:
    meal = await session.get(ImportedMeal, meal_id)
    if meal is None:
        raise ValueError("meal_not_found")
    foods = [dict(food) for food in meal.foods]
    if index < 0 or index >= len(foods):
        raise ValueError("food_not_found")
    if carbs is not None:
        foods[index]["carbs_g"] = _number(carbs)
    if quantity is not None:
        foods[index]["quantity"] = quantity.strip()[:80]
    _apply_manual_foods(meal, foods)
    await session.commit()
    return meal


async def add_food(session: AsyncSession, *, meal_id: str, name: str, carbs: float) -> ImportedMeal:
    meal = await session.get(ImportedMeal, meal_id)
    if meal is None:
        raise ValueError("meal_not_found")
    foods = [dict(food) for food in meal.foods]
    foods.append({"name": name.strip()[:200], "quantity": "", "unit": "", "carbs_g": _number(carbs), "fat_g": 0.0, "protein_g": 0.0, "fiber_g": 0.0})
    _apply_manual_foods(meal, foods)
    await session.commit()
    return meal


async def delete_food(session: AsyncSession, *, meal_id: str, index: int) -> ImportedMeal:
    meal = await session.get(ImportedMeal, meal_id)
    if meal is None:
        raise ValueError("meal_not_found")
    foods = [dict(food) for food in meal.foods]
    if index < 0 or index >= len(foods):
        raise ValueError("food_not_found")
    del foods[index]
    _apply_manual_foods(meal, foods)
    await session.commit()
    return meal


def _apply_manual_foods(meal: ImportedMeal, foods: list[dict[str, Any]]) -> None:
    meal.previous_fingerprint = meal.fingerprint
    meal.previous_calculated_carbs = meal.calculated_carbs
    meal.foods = foods
    meal.calculated_carbs = calculated_carbs(foods)
    meal.source_carbs = meal.calculated_carbs
    meal.fingerprint = content_fingerprint(
        foods=foods, source_carbs=meal.source_carbs, fat=meal.fat, protein=meal.protein, fiber=meal.fiber
    )
    meal.version = int(meal.version or 0) + 1
    meal.manual_override = True
    meal.is_stable = True
    meal.stable_read_count = max(2, int(meal.stable_read_count or 0))
    meal.validation_error = None if foods else "missing_food_items"
    meal.status = "INVALID" if meal.validation_error else (
        "UPDATED_TREATED" if meal.treatment_status == "TREATED" else "UPDATED_UNTREATED"
    )
    meal.last_seen_at = _utc_now()


async def discard_meal(session: AsyncSession, *, meal_id: str) -> ImportedMeal:
    meal = await session.get(ImportedMeal, meal_id)
    if meal is None:
        raise ValueError("meal_not_found")
    meal.discarded_fingerprint = meal.fingerprint
    meal.status = "DISCARDED"
    session.add(meal)
    await session.commit()
    return meal


async def resolve_source_conflict(
    session: AsyncSession, *, meal_id: str, use_source: bool,
    expected_pending_fingerprint: str, expected_version: int,
) -> ImportedMeal:
    meal = (
        await session.execute(
            select(ImportedMeal).where(ImportedMeal.id == meal_id).with_for_update()
        )
    ).scalars().first()
    if meal is None:
        raise ValueError("meal_not_found")
    pending = dict(meal.pending_source_version or {})
    if not pending:
        raise ValueError("source_conflict_changed")
    if (
        int(meal.version or 0) != int(expected_version)
        or not expected_pending_fingerprint
        or not str(pending.get("fingerprint") or "").startswith(
            expected_pending_fingerprint
        )
    ):
        raise ValueError("source_conflict_changed")
    if use_source:
        meal.previous_fingerprint = meal.fingerprint
        meal.previous_calculated_carbs = meal.calculated_carbs
        meal.fingerprint = str(pending["fingerprint"])
        meal.foods = list(pending.get("foods") or [])
        meal.source_carbs = _number(pending.get("source_carbs"))
        meal.calculated_carbs = _number(pending.get("calculated_carbs"))
        meal.fat = _number(pending.get("fat"))
        meal.protein = _number(pending.get("protein"))
        meal.fiber = _number(pending.get("fiber"))
        meal.validation_error = pending.get("validation_error")
        meal.manual_override = False
        meal.rejected_source_fingerprint = None
        meal.version = int(meal.version or 0) + 1
    else:
        meal.rejected_source_fingerprint = str(pending.get("fingerprint") or "") or None
    meal.pending_source_version = None
    meal.status = "INVALID" if meal.validation_error else (
        "UPDATED_TREATED" if meal.treatment_status == "TREATED" else "UPDATED_UNTREATED"
    )
    session.add(meal)
    await session.commit()
    return meal
