from __future__ import annotations

from typing import Any, Iterable, Optional

from app.services.store import DataStore


def _timestamp_ms(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    # Backward compatibility if a historical caller stored epoch seconds.
    if 0 < parsed < 10_000_000_000:
        parsed *= 1000
    return parsed


def load_active_plans(store: DataStore) -> list[dict[str, Any]]:
    try:
        data = store.load_json("active_plans.json") or {}
    except Exception:
        return []
    plans = data.get("plans", []) if isinstance(data, dict) else []
    return [dict(plan) for plan in plans if isinstance(plan, dict)]


def save_active_plans(store: DataStore, plans: Iterable[dict[str, Any]]) -> None:
    store.save_json("active_plans.json", {"plans": list(plans)})


def find_active_plan(store: DataStore, identifier: str) -> Optional[dict[str, Any]]:
    for plan in load_active_plans(store):
        if identifier in {
            str(plan.get("id") or ""),
            str(plan.get("plan_id") or ""),
            str(plan.get("treatment_id") or ""),
        }:
            return plan
    return None


def select_due_active_plan(
    plans: Iterable[dict[str, Any]],
    *,
    now_ms: int,
) -> Optional[dict[str, Any]]:
    """Return the oldest due pending plan with a non-zero planned later dose."""
    eligible: list[tuple[int, dict[str, Any]]] = []
    for raw in plans:
        plan = dict(raw)
        if plan.get("status", "pending") != "pending":
            continue
        try:
            later_u = float(plan.get("later_u_planned") or 0)
        except (TypeError, ValueError):
            continue
        if later_u <= 0:
            continue

        created_ms = _timestamp_ms(plan.get("created_at_ts"))
        if created_ms is None:
            continue

        snooze_ms = _timestamp_ms(plan.get("snooze_until_ts"))
        if snooze_ms is not None and now_ms < snooze_ms:
            continue

        try:
            later_after_min = max(0, int(plan.get("later_after_min") or 0))
        except (TypeError, ValueError):
            continue
        due_ms = created_ms + later_after_min * 60_000
        if now_ms >= due_ms:
            plan["_due_at_ts"] = due_ms
            eligible.append((due_ms, plan))

    if not eligible:
        return None
    eligible.sort(key=lambda item: item[0])
    return eligible[0][1]


def update_active_plan(
    store: DataStore,
    identifier: str,
    **changes: Any,
) -> Optional[dict[str, Any]]:
    plans = load_active_plans(store)
    updated = None
    for idx, plan in enumerate(plans):
        identifiers = {
            str(plan.get("id") or ""),
            str(plan.get("plan_id") or ""),
            str(plan.get("treatment_id") or ""),
        }
        if identifier not in identifiers:
            continue
        next_plan = {**plan, **changes}
        plans[idx] = next_plan
        updated = next_plan
        break

    if updated is not None:
        save_active_plans(store, plans)
    return updated
